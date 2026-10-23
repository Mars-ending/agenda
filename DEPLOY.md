# 议程 —— 部署与日常运行

一个人用的东西，只讲能跑起来的步骤。

## 最快的一条路（推荐）

桌面上的 `agenda-app.zip` 已经打包好了（不含数据库和令牌，服务器会自己生成）。

在 **Windows 的 PowerShell 或 Git Bash** 里，把三处替换成你的信息：

```
scp C:\Users\94725\Desktop\agenda-app.zip 你的用户@你的服务器IP:~/
ssh 你的用户@你的服务器IP
```

登录进去后：

```
sudo apt-get install -y unzip        # 没装过才需要
unzip -o ~/agenda-app.zip -d ~/
sudo bash ~/agenda-app/deploy.sh 你的域名.com
```

脚本会做完剩下的事：装 python3 → 放到 `/opt/agenda` → 起 systemd → 装 Caddy 签证书，
最后打印一行 `https://你的域名/?token=xxx`，那就是配对地址。

第一次访问如果证书还没签好，等 10–30 秒再刷新。

## 本机跑（Windows）

双击 `start.bat`，或命令行：

```
cd C:\Users\94725\Desktop\agenda-app
python server.py --port 8080
```

启动后打印一行配对地址，形如 `http://127.0.0.1:8080/?token=xxxx`。
浏览器打开它，令牌自动存下，之后正常访问 `http://127.0.0.1:8080/` 即可。

**手机临时连本机**（同一 WiFi，只能试手感）：`python server.py --host 0.0.0.0 --port 8080`，
手机打开 `http://电脑IP:8080/?token=xxx`。注意 `http://` 不是安全上下文，装不成 PWA、也没有离线。

## 手动部署（脚本失败时用）

## 上服务器（Linux）

一台 1 核 1G 的机器就够。域名已备案，DNS 指向这台机器。

**1. 放文件**

```
sudo mkdir -p /opt/agenda && sudo chown $USER /opt/agenda
scp -r server.py web /opt/agenda/          # 或 git / rsync
python3 /opt/agenda/server.py --host 127.0.0.1 --port 8080   # 先手动跑一次，确认能起来
```

第一次运行会生成 `/opt/agenda/token.txt` 和 `agenda.db`。

**2. 常驻（systemd）**

```
sudo cp deploy/agenda.service /etc/systemd/system/
sudo sed -i 's/^User=.*/User='"$USER"'/' /etc/systemd/system/agenda.service   # 换成你的用户
sudo systemctl daemon-reload
sudo systemctl enable --now agenda
sudo systemctl status agenda --no-pager
```

**3. HTTPS（Caddy，证书自动续）**

```
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile     # 把域名换成你的
sudo systemctl reload caddy
```

Caddy 会自动申请证书；`https://你的域名/` 就是 app。

**4. 每天备份（保留 7 天）**

```
crontab -e
```

```
0 4 * * * python3 -c "import sqlite3;src=sqlite3.connect('/opt/agenda/agenda.db');dst=sqlite3.connect('/opt/agenda/backup-$(date +\%F).db');src.backup(dst)" && find /opt/agenda -name 'backup-*.db' -mtime +7 -delete
```

用 SQLite 的备份 API 而不是 `cp`：WAL 模式下直接拷可能拿到半个事务。

**5. 每台设备一个令牌**

```
echo $(python3 -c "import secrets;print(secrets.token_urlsafe(24))") >> /opt/agenda/token.txt
sudo systemctl restart agenda
```

然后在每台设备上打开 `https://你的域名/?token=新令牌`，一次就行。手机丢了就删掉那一行再重启，其余设备不受影响。

## 手机装成 app

- **Android / Chrome**：打开网址 → 菜单「添加到主屏幕」
- **iPhone / Safari**：分享按钮 → 「添加到主屏幕」。**必须这一步**，否则 iOS 收不到通知

## 已知边界

- 冲突按「后写覆盖先写」，用客户端时间判断。单人双设备够用；如果两台设备同时改同一条，晚提交的那条赢
- 每次同步是全量拉「上次游标之后」的变更，不压缩；几千条以内没有感觉
- 没有服务端推送。手机上的提醒要等打开 app 时同步；桌面端可以自己挂一个本地通知任务去 `/sync` 取
- `token.txt` 明文存令牌，权限 600；服务器被拿到 root 就等于拿到数据
