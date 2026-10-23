# 议程

一个人的议程：**一次事 / 惯例 / 目标 / 日记** 四类分开管，重要性靠「钉住」而不是打分。
PWA 前端 + 单文件 Python 后端，离线先写、联网补同步。

## 它解决什么

待办清单的两种死法：惯例每天生成一条「未完成」，三天把列表堆满；目标永远排在最后一页。
所以四类事按「多久会过期」分容器，用四套机制推进：

| 类型 | 会过期 | 机制 |
|---|---|---|
| 一次事 | 会 | 排期 + 完成/推迟 |
| 惯例 | 不会 | 连击 + 有上限的宽恕（断一天可接上） |
| 目标 | 不会 | 里程碑 + 周检查，不进今天 |
| 日记 | 不适用 | 只写不催，挂在事上的想法 |

设计依据（Lally 2010、Silverman & Barasch 2022、Duolingo 冻结机制、Li 等 CHI 2010、Things 3 / OmniFocus / 滴答清单的产品结构）见 `docs/model-research.md`。

## 跑起来

```
python server.py --port 8080
```

打开它打印的 `http://127.0.0.1:8080/?token=xxx`，令牌自动存下。Windows 可直接双击 `start.bat`。

## 上服务器

见 `DEPLOY.md`。一条命令：

```
sudo bash deploy.sh 你的域名.com
```

## 结构

```
server.py            后端：SQLite + /sync + 令牌 + 静态托管（纯标准库，零依赖）
web/index.html       前端：单文件，三屏 + 惯例 + 目标 + 日记 + 同步队列
web/manifest.json    装成 app
web/sw.js            离线缓存（网络优先）
deploy.sh / deploy/  systemd + Caddy
```

## 同步协议

- 客户端生成 UUID，服务端只分配递增 `seq`
- 拉取用游标：`since=<seq>` 之后的全量变更
- 删除写墓碑，不真删
- 冲突按 `updated_at` 后写覆盖先写（单人双设备够用，不做 CRDT）
- 每台设备一个令牌，丢设备就吊销那一行

## 注意

`token.txt` 和 `agenda.db` 已在 `.gitignore` 里，**不要提交**。数据库用 SQLite 的备份 API 拷，不要在运行中直接 `cp`。
