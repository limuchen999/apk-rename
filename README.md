# apk_rename

在 Android Termux 环境下使用的 APK 包名一键修改脚本。

自动完成：**反编译 → 修改包名 → 回编译 → 签名 → 验证**，全程只需按提示输入几个参数。

---

## 特性

- **一键流程**：从环境检测到最终签名输出，全自动串联
- **自动装环境**：检测缺失依赖（`openjdk-17` / `apktool` / `apksigner` / `zipalign` / `keytool`），缺失时询问后自动 `pkg install`
- **交互式输入**：APK 路径、新包名、签名信息等，均带格式校验
- **只改 manifest，不碰 smali**：避免 JNI 符号错位、类路径错乱，是修改包名最安全的做法
- **同步所有「全局唯一标识」**：改包名时一并处理会导致安装冲突的所有字段
- **性能优化**：反编译使用 `-s`（跳过 smali），回编译使用 `--no-crunch`（跳过资源压缩）
- **完整验证**：签名验证（v2/v3）+ 包名验证，双重确认
- **原 APK 不动**：输出到源 APK 同目录，文件名为 `<原名>_modded.apk`
- **日志与清理**：日志保留在 `~/.apk_rename_logs/`，临时文件自动清理

---

## 修改的内容

脚本只修改 `AndroidManifest.xml` 中会导致「与已安装应用冲突」的字段，**绝不修改任何组件类名**（`<activity>` / `<service>` / `<receiver>` / `<provider>` 的 `android:name`）。

具体修改：

| 字段 | 说明 |
|------|------|
| `<manifest>` 的 `package` | 应用包名 |
| `<permission>` / `<uses-permission>` 的 `android:name` | 自定义权限名 |
| `<provider>` 的 `android:authorities` | ContentProvider 授权名（支持分号分隔多个） |
| `android:permission` / `readPermission` / `writePermission` | 组件权限 |
| `android:taskAffinity` | 任务栈归属 |
| `android:process` | 进程名 |
| `<data android:scheme>` | 以包名开头的 scheme |

---

## 环境要求

- Android 手机
- Termux（F-Droid 版本或 GitHub 版本）
- 存储权限（首次使用需执行一次 `termux-setup-storage`）

脚本运行时会自动检测并安装以下依赖：

    openjdk-17
    apktool
    apksigner
    zipalign

---

## 安装

    # 1. 授权存储访问（只需一次）
    termux-setup-storage

    # 2. 更新 pkg 源（可选，建议）
    pkg update

    # 3. 保存脚本
    # 把本仓库的 apk_rename.py 复制到任意目录，例如：
    nano ~/apk_rename.py
    # 粘贴脚本内容，Ctrl+O 保存，Ctrl+X 退出

---

## 使用

    python apk_rename.py

脚本会依次询问：

### 1. APK 文件路径

    > /storage/emulated/0/Download/app.apk

示例：`/storage/emulated/0/Download/`、`/sdcard/Download/` 均可。

### 2. 新包名

    > com.example.myapp

规则：至少 2 段，用点分隔，每段以字母开头，只能含字母/数字/下划线。

### 3. 签名配置

- **已有 keystore** → 输入路径、别名、密码
- **没有** → 留空自动生成新密钥，保存到 `~/apk_keys/mykey.keystore`

### 4. 输出重名处理

若目标位置已有同名 `_modded.apk`，会询问：`覆盖(o) / 重命名(r) / 取消(c)`

### 5. 确认执行

打印执行计划后，输入 `y` 回车开始。

---

## 输出示例

    ========== 执行计划 ==========
      源 APK    : /storage/emulated/0/Download/v2rayNG.apk
      新包名    : com.text.v2rayng
      输出位置  : /storage/emulated/0/Download/v2rayNG_modded.apk
      临时目录  : /data/data/com.termux/files/home/.apk_rename_build
      日志文件  : /data/data/com.termux/files/home/.apk_rename_logs/v2rayNG_20261007_082710.log
      签名密钥  : /data/data/com.termux/files/home/apk_keys/mykey.keystore
    ==============================

    确认开始？[Y/n]: y

    【1/6】反编译 APK
    [✓] 反编译（跳过 smali）完成（耗时 15s）

    【2/6】修改包名
    [*] 原包名: com.v2ray.ang
    [✓] 包名已修改为: com.text.v2rayng

    【3/6】回编译 APK
    [✓] 回编译（跳过资源压缩）完成（耗时 21s）

    【4/6】签名 APK
    [✓] 签名成功

    【5/6】验证结果
    [✓] 签名验证通过
    [✓] 包名验证通过: com.text.v2rayng

    【6/6】输出结果
    [✓] 已复制到源 APK 同目录
    [✓] 临时文件已清理

    ========== 结果摘要 ==========
    [✓] 输出文件  : /storage/emulated/0/Download/v2rayNG_modded.apk
      文件大小  : 31.5 MB
      原包名    : com.v2ray.ang
      新包名    : com.text.v2rayng
      总耗时    : 45s
    ==============================

---

## 性能

在 Termux + Android 手机（8 核 ARM）上的实测数据（31 MB APK，含 5 个 dex）：

| 阶段 | 原方案 | 本脚本 | 提升 |
|------|--------|--------|------|
| 反编译 | ~99s | ~15s | 6.6× |
| 回编译 | ~160s | ~21s | 7.6× |
| **总计** | **~290s** | **~45s** | **6.5×** |

优化点：

- **反编译** 使用 `-s`（`--no-src`）：不反编译 dex，直接复制原始 dex 到工作目录
- **回编译** 使用 `--no-crunch`：不重新压缩 `res/` 中的图片资源
- 由于本脚本**不修改代码**，以上两项优化完全安全

---

## 工作目录

| 路径 | 用途 | 是否保留 |
|------|------|---------|
| `~/.apk_rename_build/` | 反编译产物与临时构建目录 | 脚本结束时清理 |
| `~/.apk_rename_logs/` | 运行日志 | 保留，便于排查 |
| `~/apk_keys/` | 自动生成的签名密钥 | 保留，**必须妥善保管** |

---

## 注意事项

### 1. 签名密钥

- 自动生成的密钥保存在 `~/apk_keys/mykey.keystore`
- **后续更新同一个改过包名的 APK，必须使用同一密钥**
- 否则系统会因签名冲突而拒绝覆盖安装
- 建议把密钥文件和密码备份到安全的地方

### 2. 兼容性

以下情况修改包名后可能无法正常运行：

- **应用带签名校验**（SafetyNet / Play Integrity / 自研校验）
- **应用含 native 库（.so）**，且 JNI 符号名硬编码了原包名（如 `Java_com_xxx_yyy_Method`）
- **应用依赖 `BuildConfig.APPLICATION_ID`** 做服务端校验
- **应用使用 AndroidX Startup / WorkManager / JobScheduler** 等按包名隔离的组件时，可能出现行为异常

遇到闪退时用 logcat 排查：

    logcat -d -t 200 | grep -iE "AndroidRuntime|UnsatisfiedLink|FATAL" | tail -40

### 3. 法律合规

- 本工具仅用于**个人学习、测试与合法用途**
- 修改、分发他人 APK 可能违反原应用的许可协议或当地法律
- 请自行评估风险

---

## 常见问题

**Q：为什么回编译不重新汇编 smali？**

A：反编译使用 `-s`（`--no-src`），dex 原样保留；回编译时直接复制原始 dex，跳过 smali 汇编。本脚本只改 manifest、不改代码，该优化完全安全。

**Q：为什么输出 APK 比原 APK 大 0.1~0.5 MB？**

A：三个原因：
1. `--no-crunch` 跳过了图片资源压缩
2. 重新签名生成新的签名块（v2/v3 方案元数据）
3. `zipalign -p` 的页对齐填充

属正常现象，不影响功能。

**Q：修改后能覆盖安装到原应用上吗？**

A：**不能**。包名改了就是新应用，会与原应用**共存**。这是修改包名的核心目的（如双开）。如果只想升级原应用，不要改包名。

**Q：脚本执行中断了怎么办？**

A：
- 查看日志：`ls -t ~/.apk_rename_logs/ | head -1` 找到最新日志
- 反编译目录可能残留在 `~/.apk_rename_build/`，可手动删除
- 原 APK 不受影响，可重新运行

**Q：支持修改应用显示名（桌面名称）吗？**

A：当前脚本只改包名。如需同时改显示名，需额外修改 `AndroidManifest.xml` 中 `<application android:label>` 的引用值。欢迎 PR。

---

## License

MIT
