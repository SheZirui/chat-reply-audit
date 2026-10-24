# 本地审查与未来发布

此目录是一份可供人工审查的源代码包。**准备好本地目录不等于已经发布，演示页面也不是在线站点。**

## 内容来源

程序为通用CSV/JSON分析、审阅和报告实现，使用Python标准库；没有内置聊天软件数据库读取、进程扫描、密钥提取或第三方解密代码。

`examples/demo.csv`、阶段、审阅答案和展示图均由`scripts/build_demo.py`中的固定虚构场景生成。日期为虚构演示日期，人物只有A/B。它们不是从某个真实会话改名或抽样得到。

## 自己审查时重点看

1. README说明的能力和限制是否符合你想公开的项目定位。
2. SKILL.md是否明确要求授权范围、按原文取证、保留不确定性及区分API发送。
3. scripts/是否存在本机路径、账号、凭据、网络上传或不必要的数据读取。
4. examples/、assets/是否只包含虚构内容；HTML是否含外部资源或真实摘录。
5. LICENSE的MIT选择是否符合你的发布意愿；不要为项目补写不真实的署名。
6. 本地实际测试、模拟API测试与真实API验证是否明确区分。此包没有真实服务的联调记录，不宣称已验证所有模型提供方。

## 检查命令

```powershell
python -B -m unittest discover -s tests -v
python -B scripts/build_demo.py --check
python -B scripts/privacy_check.py
```

修改源码或演示产物后，需要人工查看改动，再重建摘要清单：

```powershell
python -B scripts/privacy_check.py --update-manifest
```

该命令仍会执行通用敏感模式扫描与文件白名单检查；它不能替你判断所有个人信息。不要为通过扫描而随意扩大白名单。

## 需要新的干净副本时

```powershell
python scripts/export_release.py --out ../chat-reply-audit-release
```

目标须为全新目录，程序只复制白名单文件及摘要清单，随后再次校验。不会初始化Git、创建远程仓库或上传。

## 未来上传时

从这份单独检查过的公开目录创建全新仓库，不从保存实际聊天、数据库或凭据的上层目录直接推送。`.gitignore`不影响已经被Git跟踪过的文件，也不能清除历史。

确认文件后再选择仓库名、公开性、作者与许可证，并由你明确决定上传。README没有虚构的GitHub地址、发布徽章或下载链接；仓库真正建立后再补真实链接。分享截图可直接使用assets中的虚构展示图，避免截到本机路径、API配置或私人报告。
