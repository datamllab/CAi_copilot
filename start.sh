#!/bin/bash
# 1. 切换到项目代码目录
cd /mnt/shared-storage-gpfs2/chenjiangyu-gpfs02/CAi_copilot

# export http_proxy="http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
# export https_proxy="http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
# export no_proxy="10.0.0.0/8,100.96.0.0/12,.pjlab.org.cn,localhost,127.0.0.1,0.0.0.0"

# export HTTP_PROXY="http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
# export HTTPS_PROXY="http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
# export NO_PROXY="10.0.0.0/8,100.96.0.0/12,.pjlab.org.cn,localhost,127.0.0.1,0.0.0.0"

echo "✔ 实验室内部代理已成功开启"
/mnt/shared-storage-gpfs2/chenjiangyu-gpfs02/miniconda3/envs/bio_demo/bin/python CAi/main.py