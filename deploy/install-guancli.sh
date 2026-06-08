#!/bin/bash
# 阿里云 ECS 安装观远 guancli
# 用法: sudo bash deploy/install-guancli.sh
set -e

echo "==> 检查 Node.js (需要 20+，推荐 22+)"

install_node_ubuntu() {
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
}

install_node_centos() {
  curl -fsSL https://rpm.nodesource.com/setup_22.x | bash -
  yum install -y nodejs
}

if ! command -v node >/dev/null 2>&1; then
  if command -v apt-get >/dev/null; then
    install_node_ubuntu
  elif command -v yum >/dev/null; then
    install_node_centos
  else
    echo "请手动安装 Node.js 22+: https://nodejs.org/"
    exit 1
  fi
fi

NODE_VER=$(node -p "process.version.replace('v','').split('.')[0]")
if [ "$NODE_VER" -lt 20 ] 2>/dev/null; then
  echo "Node 版本过低: $(node -v)，需要 20+"
  exit 1
fi
echo "Node $(node -v)  npm $(npm -v)"

echo "==> 安装 @guandata/guancli"
npm install -g @guandata/guancli

GUANCLI_BIN=$(command -v guancli)
echo "guancli 已安装: $GUANCLI_BIN"
guancli version

mkdir -p /root/.config/guancli

if [ -f /root/.config/guancli/config.json ]; then
  echo "==> 已有配置文件，跳过登录"
  guancli auth status || true
  echo "==> 复制 guancli 配置供 www-data 服务使用"
  mkdir -p /var/www/.config/guancli
  cp /root/.config/guancli/config.json /var/www/.config/guancli/
  chown -R www-data:www-data /var/www 2>/dev/null || chown -R www:www /var/www 2>/dev/null || true
else
  echo ""
  echo "============================================================"
  echo "  尚未配置 BI 凭证，请任选一种方式："
  echo ""
  echo "  方式 A（推荐）在 Mac 上复制已有配置："
  echo "    ssh root@101.133.149.106 'mkdir -p /root/.config/guancli'"
  echo "    scp \"\$HOME/Library/Application Support/guancli/config.json\" \\"
  echo "        root@101.133.149.106:/root/.config/guancli/config.json"
  echo ""
  echo "  方式 B 在服务器上交互登录："
  echo "    guancli auth login"
  echo "    # URL: https://bi.marius.vip  Domain: guanbi"
  echo ""
  echo "  配置完成后验证："
  echo "    guancli auth status"
  echo "    guancli ds preview r6d0ada08a78746bca88007e --limit 1 --format json"
  echo "============================================================"
fi
