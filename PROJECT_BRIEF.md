# 中创新航 IPAM 系统实施项目

## 项目概述

基于已有的前端HTML设计原型，实现一个完整的企业级IP地址管理系统（IPAM），服务于中创新航工厂网络环境。

## 技术栈要求

### 后端
- **Python**: 3.11+
- **Django**: 5.0.1
- **数据库**: PostgreSQL 15
- **任务队列**: django-q2 (用于SNMP扫描)
- **SNMP**: pysnmp-lextudio (网络设备扫描)
- **加密**: cryptography (SNMP凭证加密存储)

### 前端
- **框架**: Django Templates (将HTML原型转换为Django模板)
- **CSS**: Tailwind CSS 3.4+ (离线部署，编译为静态文件)
- **图标**: Material Symbols Outlined (离线字体文件)
- **字体**: Inter (离线部署)
- **交互**: Alpine.js 3.14+ (轻量级响应式交互)
- **主题**: 暗黑模式为主（dark mode）

### 部署
- **容器化**: Docker + Docker Compose
- **Web服务器**: Gunicorn + Nginx
- **网络**: 局域网内网部署
- **访问地址**: http://10.21.111.129

## 已有资源

### 前端HTML原型（calb-ipim/目录）
包含12个完整页面设计，每个页面包含：
- `code.html` - 完整的HTML代码
- `screen.png` - 视觉效果截图

**页面清单**：
1. ✅ 登录页面 - 带中创新航品牌的暗黑风格登录界面
2. ✅ 仪表板 - 网络资源概览、统计图表、高负载监控、操作日志
3. ✅ IP地址管理列表 - 支持搜索、筛选、批量操作的IP列表
4. ✅ IP地址详情 - 单个IP的详细信息和历史记录
5. ✅ IP地址选择 - 可视化网格选择可用IP
6. ✅ IP地址绑定向导 - 多步骤向导（选择子网→选择IP→填写设备信息）
7. ✅ 子网管理列表 - CIDR子网列表和管理
8. ✅ 子网详情 - 子网使用率、IP分布可视化
9. ✅ 审计日志列表 - 完整的操作审计追踪
10. ✅ 用户管理界面 - 用户和角色权限管理
11. ✅ ARP扫描与统计界面 - 网络设备扫描结果展示
12. ✅ 设备信息填写 - IP分配时的设备信息表单

### 设计系统

**颜色规范**：
```javascript
{
  "primary": "#2463eb",           // 主色调（蓝色）
  "background-light": "#f6f6f8",  // 浅色背景
  "background-dark": "#111621",   // 暗黑背景
  "surface-dark": "#1e2430",      // 暗黑表面
  "border-dark": "#2a3241",       // 暗黑边框
  "text-secondary": "#9da6b9"     // 次级文本
}
```

**排版**：
- 字体：Inter (display字体，支持中文fallback到微软雅黑)
- 等宽字体：SFMono, Monaco, Consolas (用于IP地址显示)

**图标**：
- Material Symbols Outlined (outlined风格，可配置fill/weight)

## 核心功能需求

### 1. 用户认证与权限
- Django内置用户系统
- 基于角色的权限控制（管理员、网络工程师、普通用户）
- 会话超时：30分钟
- 审计所有敏感操作

### 2. IP地址管理
- **状态管理**：可用、已分配、保留、冲突
- **并发分配保护**：数据库行锁 + CAS原子更新
- **自助分配向导**：
  - Step 1: 选择子网
  - Step 2: 可视化网格选择IP（参考IP地址选择.html）
  - Step 3: 填写设备信息（主机名、MAC、用途、责任人）
- **批量操作**：批量释放、批量保留
- **IP详情页**：显示分配历史、SNMP扫描记录、ARP信息

### 3. 子网管理
- CIDR表示法（如192.168.10.0/24）
- 自动初始化IP池（创建子网时批量生成IP记录）
- 子网统计：总IP数、可用数、已分配数、保留数、使用率
- 子网可视化：IP分布热力图或网格视图

### 4. SNMP网络扫描
- 异步任务队列（django-q2）
- 支持SNMPv2c和SNMPv3
- 扫描周期：600秒（可配置）
- 扫描内容：ARP表（OID: 1.3.6.1.2.1.4.22.1.2）
- **冲突检测**：已分配IP的MAC地址变化自动标记为冲突
- SNMP凭证加密存储（Fernet对称加密）

### 5. 审计日志
- 记录所有IP操作（分配、释放、更新、删除）
- 记录操作人、时间、IP地址、操作类型、设备信息
- 支持按时间、用户、IP、操作类型筛选
- 不可修改（immutable）

### 6. 仪表板
- **统计卡片**：
  - 子网数量
  - 总IP数
  - 可用IP
  - 已分配IP
  - 保留IP
  - 冲突IP（红色警告）
- **图表**：
  - IP状态分布（饼图）
  - IP分配趋势（30天折线图）
- **高负载子网监控**：显示使用率>80%的子网
- **最近操作日志**：最新10条审计记录

## 部署要求

### 离线部署（无互联网访问）

**关键点**：
- ❌ 不能使用CDN加载Tailwind CSS
- ❌ 不能使用Google Fonts CDN
- ❌ 不能使用在线图片资源
- ✅ 所有依赖必须本地化

**实现方案**：

1. **Tailwind CSS**：
   ```bash
   # 在backend/static/目录下安装
   npm install -D tailwindcss @tailwindcss/forms
   # 编译为静态CSS文件
   npx tailwindcss -i ./src/input.css -o ./dist/tailwind.compiled.css --minify
   ```

2. **字体文件**：
   - 下载Inter字体文件到`static/fonts/Inter/`
   - 下载Material Symbols Outlined字体到`static/fonts/material-symbols/`
   - 在CSS中使用`@font-face`本地加载

3. **Python依赖**：
   ```bash
   # 提前下载wheel包到本地
   pip download -r requirements.txt -d ./packages
   # 离线安装
   pip install --no-index --find-links=./packages -r requirements.txt
   ```

### Docker Compose配置

**网络配置**：
```yaml
services:
  web:
    ports:
      - "10.21.111.129:80:8000"  # 绑定到指定IP
    environment:
      - ALLOWED_HOSTS=10.21.111.129,localhost
      - CSRF_TRUSTED_ORIGINS=http://10.21.111.129
```

**环境变量**：
```env
# 安全配置
SECRET_KEY=<生成64字符随机密钥>
ENCRYPTION_KEY=<生成32字符Fernet密钥>
DEBUG=0

# 数据库
DB_NAME=ipam_db
DB_USER=ipam_user
DB_PASSWORD=<强密码>
DB_HOST=db
DB_PORT=5432

# 网络
ALLOWED_HOSTS=10.21.111.129,localhost
CSRF_TRUSTED_ORIGINS=http://10.21.111.129

# SNMP
SNMP_TIMEOUT=5
SNMP_SCAN_INTERVAL=600
```

### 浏览器缩放优化

**问题**：Tailwind的响应式设计在某些缩放比例下可能显示异常

**解决方案**：

1. **Viewport Meta标签**：
   ```html
   <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
   ```

2. **CSS缩放适配**：
   ```css
   /* 针对常见浏览器缩放比 */
   @media (min-width: 1920px) {
     html { font-size: 16px; }
   }
   @media (min-width: 2560px) {
     html { font-size: 18px; }
   }
   ```

3. **rem单位替代px**：
   - 使用Tailwind的默认rem单位
   - 关键尺寸（侧边栏256px、表格列宽）使用百分比或flex

4. **最佳浏览器设置**：
   - 推荐缩放：100%（默认）
   - 支持范围：80% - 125%
   - 最小分辨率：1366x768

## 数据模型设计

### 核心模型

**Subnet**（子网）：
- `network` - CharField, CIDR格式（如192.168.10.0/24）
- `gateway` - GenericIPAddressField
- `netmask` - GenericIPAddressField
- `vlan_id` - IntegerField (可选)
- `description` - TextField
- `created_at` / `updated_at` - DateTimeField

**IpAddress**（IP地址）：
- `subnet` - ForeignKey(Subnet)
- `address` - GenericIPAddressField (唯一索引)
- `status` - CharField choices: available/allocated/reserved/conflict
- `hostname` - CharField (可选)
- `mac_address` - CharField (可选)
- `device_type` - CharField (如：服务器、打印机、工控机)
- `department` - CharField (使用部门)
- `responsible_person` - CharField (责任人)
- `allocated_at` - DateTimeField (分配时间)
- `allocated_by` - ForeignKey(User)
- `notes` - TextField

**NetworkDevice**（网络设备 - 用于SNMP扫描）：
- `name` - CharField
- `ip_address` - GenericIPAddressField
- `snmp_version` - CharField choices: v2c/v3
- `snmp_community` - CharField (v2c密钥)
- `snmp_username` / `snmp_auth_password_encrypted` / `snmp_priv_password_encrypted` (v3凭证)
- `enabled` - BooleanField (是否启用扫描)
- `last_scan_at` - DateTimeField

**AuditLog**（审计日志）：
- `timestamp` - DateTimeField (自动添加)
- `user` - ForeignKey(User)
- `action` - CharField choices: allocate/release/update/delete
- `ip_address` - CharField
- `hostname` - CharField
- `mac_address` - CharField
- `details` - JSONField (额外信息)

## 实施步骤建议

### Phase 1: 环境搭建 (Day 1-2)
1. 创建Docker Compose配置
2. 配置PostgreSQL数据库
3. 设置Django项目结构
4. 离线部署Tailwind CSS和字体文件
5. 配置静态文件服务

### Phase 2: 后端核心 (Day 3-5)
1. 创建数据模型（Subnet, IpAddress, NetworkDevice, AuditLog）
2. 实现Django Admin管理界面
3. 编写API视图（RESTful JSON API）
4. 实现IP分配的并发控制逻辑
5. 配置django-q2任务队列

### Phase 3: SNMP扫描 (Day 6-7)
1. 实现SNMP扫描任务
2. ARP表解析和冲突检测
3. 周期性扫描调度
4. SNMP凭证加密存储

### Phase 4: 前端转换 (Day 8-12)
1. 将HTML原型转换为Django模板
2. 实现侧边栏导航组件
3. 创建可复用组件（状态徽章、表格、卡片）
4. 实现IP选择网格视图
5. 集成Alpine.js交互逻辑
6. 实现IP分配向导（多步骤表单）

### Phase 5: 测试与优化 (Day 13-14)
1. 并发分配压力测试
2. SNMP扫描功能测试
3. 浏览器兼容性测试（不同缩放比）
4. 性能优化（数据库索引、查询优化）
5. 安全审计

### Phase 6: 文档与部署 (Day 15)
1. 编写部署文档
2. 创建用户使用手册
3. 准备离线安装包
4. 生产环境部署

## 关键技术难点

### 1. 并发IP分配
**问题**：多用户同时选择同一IP导致冲突

**解决方案**：
```python
from django.db import transaction

@transaction.atomic
def allocate_ip(ip_id, user, device_info):
    # 数据库行锁
    ip = IpAddress.objects.select_for_update().get(pk=ip_id)
    
    if ip.status != 'available':
        raise ValueError("IP不可用")
    
    # CAS原子更新验证
    updated = IpAddress.objects.filter(
        pk=ip_id, 
        status='available'
    ).update(
        status='allocated',
        hostname=device_info['hostname'],
        # ...
    )
    
    if updated == 0:
        raise ValueError("分配失败，IP已被占用")
```

### 2. 离线Tailwind CSS
**问题**：原型HTML使用CDN，需要本地化

**步骤**：
1. 提取所有HTML中使用的Tailwind类
2. 创建`tailwind.config.js`，定义自定义颜色
3. 编译为单个CSS文件
4. 模板中引入：`<link href="{% static 'css/tailwind.compiled.css' %}">`

### 3. IP可视化网格
**问题**：256个IP（/24子网）的交互式网格

**方案**：
- 使用CSS Grid布局：`grid-template-columns: repeat(16, minmax(0, 1fr))`
- Alpine.js管理选中状态
- 颜色编码：绿色（可用）、蓝色（已分配）、黄色（保留）、红色（冲突）
- Hover效果和点击选择

### 4. SNMP v3加密
**挑战**：SNMPv3需要认证和加密参数

**实现**：
```python
from pysnmp.hlapi import *

def scan_snmp_v3(device):
    auth_key = device.get_snmp_auth_password()  # 解密
    priv_key = device.get_snmp_priv_password()
    
    iterator = getCmd(
        SnmpEngine(),
        UsmUserData(
            device.snmp_username,
            authKey=auth_key,
            privKey=priv_key,
            authProtocol=usmHMACSHAAuthProtocol,
            privProtocol=usmAesCfb128Protocol
        ),
        UdpTransportTarget((device.ip_address, 161), timeout=5),
        ContextData(),
        ObjectType(ObjectIdentity('1.3.6.1.2.1.4.22.1.2'))  # ARP表
    )
    # 处理结果...
```

## 验收标准

### 功能验收
- [ ] 用户可以登录并根据角色看到不同菜单
- [ ] 可以创建子网并自动生成IP池
- [ ] IP分配向导完整可用（3步骤）
- [ ] 可视化网格选择IP正常工作
- [ ] 两个用户同时分配同一IP时只有一个成功
- [ ] SNMP扫描每10分钟自动运行
- [ ] 检测到MAC地址变化时IP自动标记为冲突
- [ ] 所有操作记录到审计日志
- [ ] 仪表板统计数据准确

### 性能验收
- [ ] 10,000个IP记录下页面加载<2秒
- [ ] 并发10用户分配IP无冲突
- [ ] SNMP扫描100个设备<5分钟

### 界面验收
- [ ] 暗黑主题一致应用
- [ ] 所有页面100%匹配原型设计
- [ ] 浏览器缩放80%-125%下布局不错乱
- [ ] 移动端（768px以下）响应式正常

### 部署验收
- [ ] 完全离线环境可部署成功
- [ ] 从10.21.111.129可正常访问
- [ ] Docker容器可自动重启
- [ ] 数据库数据持久化

## 品牌要求

- **公司名称**：中创新航
- **Logo**：蓝色hub图标 + 公司名称
- **Slogan**：工厂 IP 地址管理系统
- **色调**：专业、工业、科技感
- **语言**：简体中文
- **时区**：Asia/Shanghai

## 安全要求

1. **密码策略**：
   - 最小8位
   - 必须包含字母+数字
   - Django PBKDF2加密存储

2. **会话管理**：
   - 30分钟无操作自动登出
   - 仅HTTP（内网环境，不需要HTTPS）
   - CSRF保护启用

3. **敏感数据加密**：
   - SNMP凭证使用Fernet加密
   - 加密密钥从环境变量读取
   - 不在日志中记录明文凭证

4. **审计追踪**：
   - 所有IP操作必须记录
   - 日志不可修改
   - 记录用户IP地址

## 交付物清单

1. **代码仓库**：
   - 完整Django项目
   - Docker配置文件
   - requirements.txt

2. **静态资源**：
   - 编译后的Tailwind CSS
   - 离线字体文件
   - 图标资源

3. **数据库**：
   - 迁移文件
   - 初始数据（超级用户、示例子网）

4. **文档**：
   - 部署指南（离线环境）
   - 用户操作手册
   - API文档
   - 数据库ER图

5. **测试**：
   - 单元测试（pytest）
   - 并发测试用例
   - Postman API测试集合

## 参考资料

- Django 5.0文档：https://docs.djangoproject.com/en/5.0/
- Tailwind CSS文档：https://tailwindcss.com/docs
- pysnmp-lextudio文档：https://pysnmp.readthedocs.io/
- Material Symbols：https://fonts.google.com/icons

---

**预计工期**：15个工作日
**团队配置**：1后端工程师 + 1前端工程师（可由AI辅助完成）
**优先级**：P0（核心生产系统）
