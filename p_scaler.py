# Copyright 2016 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Shows how to load a Kubernetes config from outside of the cluster.
https://github.com/kubernetes-client/python
"""
import math
import time
import argparse
import requests
from datetime import datetime, timedelta
from kubernetes import client, config
DEPLOYMENTS = ["teastore-webui", "teastore-persistence", "teastore-auth", "teastore-recommender", "teastore-image"]
DEPLOYMENT_NAME = "teastore-webui"
CPU=0.7
MAX_PRESSURE = 0.2
PROMETHEUS_IP = ""
TEASTORE_URL = "172.16.52.8:9100"
PROMETHEUS_URL = "http://172.16.52.9:30090"


def cpu_convert(val):
    if "n" in val:
        val = val.strip("n")
        return int(val)*1e-9
    elif "u" in val:
        val = val.strip("u")
        return int(val)*1e-6
    

def update_deployment(api, deployment, replicas, name):
    # Update container image
    deployment.spec.replicas = replicas

    # patch the deployment
    resp = api.patch_namespaced_deployment(
        name=name, namespace="default", body=deployment
    )

    print("\n[INFO] deployment's container image updated.\n")
    print("%s\t%s\t\t\t%s" % ("NAMESPACE", "NAME", "replicas"))
    print(
        "%s\t\t%s\t\t\t%s\n"
        % (
            resp.metadata.namespace,
            resp.metadata.name,
            resp.spec.replicas,
        )
    )


def main():
    # Configs can be set in Configuration class directly or using helper
    # utility. If no argument provided, the config will be loaded from
    # default location.
    parser = argparse.ArgumentParser(description='')
    args = parser.parse_args()

    config.load_kube_config()
    #https://github.com/kubernetes-client/python/
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    custom_api = client.CustomObjectsApi()
    
    nodes = []
    url = PROMETHEUS_URL + '/api/v1/query_range?'

    while True:
        MAX_CPU = 0.7
        # get memory pressure rate which is per-second average rate of increase (here over 60 seconds)
        # node_pressure_memory_waiting_seconds_total is a counter metric so need to use rate
        payload_mem = {'query': "rate(node_pressure_memory_waiting_seconds_total{instance='"+ TEASTORE_URL +"'}[60s])", 'start': (datetime.now()-timedelta(seconds=10)).timestamp(), 'end': datetime.now().timestamp(), 'step': '1s'}
        # maybe check node_pressure_memory_stalled_seconds_total first (time all tasks were stalled)
        cpu_pressure = 0
        mem_pressure = 0

        try: 
            mem_res = requests.post(url, headers={'Content-Type': 'application/x-www-form-urlencoded'}, data=payload_mem).json()

            cpu_pressures = 0
            mem_pressures = 0

            for val in mem_res["data"]["result"][0]["values"]:
                mem_pressures += float(val[1])

            mem_pressure = mem_pressures/len(mem_res["data"]["result"][0]["values"])

        except Exception as e:
            print(e)
            mem_pressure = 1

        print("#####################")
        print("memory pressure ", mem_pressure)
        down =False
        if mem_pressure > 0:
            down = True
            MAX_CPU = 0.8
            print("downscale")

        for dep_name in DEPLOYMENTS:
            pods = v1.list_namespaced_pod("default", label_selector="run=" + dep_name, field_selector="status.phase=Running")
            cpus = []
            print(dep_name)
            for pod in pods.items:
                info = custom_api.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "pods", field_selector="metadata.name=" + pod.metadata.name)

                if not info and not info['items'] and not info['items'][0]['containers']:
                    print("no res")
                    continue
                
                g_cpu = 0
                try:
                    g_cpu = cpu_convert(info['items'][0]['containers'][0]['usage']['cpu'])
                except Exception as e:
                    print(e)
                    continue

                if g_cpu:
                    cpus.append(g_cpu)
                    print("cpu ", g_cpu)
            
            n_pods = len(pods.items)
            avg_cpu = sum(cpus)/n_pods 
            sum_cpu = sum(cpus) 
            print("max cpu", MAX_CPU)
            new_pods = max(math.ceil(sum_cpu/MAX_CPU), 1)

            print("avg cpu ", avg_cpu)
            print("prev pods", n_pods)
            print("new pods", new_pods)

            new_pods = min(10, 0)

            if mem_pressure >= 0.1:
                new_pods = 1

            if n_pods!=new_pods:
                deployment = apps_v1.read_namespaced_deployment(name=dep_name, namespace='default')
                print("scale ", dep_name)

                if down and n_pods < new_pods:
                    print("No upscaling")
                    continue
                
                update_deployment(apps_v1, deployment, new_pods, dep_name)

        time.sleep(10)


if __name__ == '__main__':
    main()
