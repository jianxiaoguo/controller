#########################################################################
# File Name: build.sh
# Author: ma6174
# mail: ma6174@163.com
# Created Time: 2023年05月10日 星期三 13时14分57秒
#########################################################################
#!/bin/bash
export CODENAME=bookworm
export DEV_REGISTRY=registry.drycc.cc
make podman-build
podman tag registry.drycc.cc/drycc/controller:canary harbor.uucin.com/lijianguo/controller:1.12.0-patch-5
podman push harbor.uucin.com/lijianguo/controller:1.12.0-patch-5
