# feat: 登录界面优化 - 忘记密码弹窗 + 修改密码功能

## Overview

优化登录界面，删除底部的隐私政策和帮助中心链接，为"忘记密码"添加联系信息弹窗，并新增用户自助修改密码功能。

## Problem Statement / Motivation

1. **隐私政策/帮助中心链接无实际用途** - 当前登录页面底部存在占位链接，未链接到实际页面
2. **忘记密码无响应** - 点击"忘记密码"链接（`href="#"`）没有任何反应，用户不知道如何重置密码
3. **缺少自助修改密码功能** - 用户无法自行修改密码，必须联系管理员

## Proposed Solution

### 1. 删除底部无用链接
移除 `login.html` 模板中的隐私政策和帮助中心链接

### 2. 忘记密码弹窗
使用 Alpine.js 实现模态弹窗，显示联系信息：
- 弹窗标题："忘记密码？"
- 内容：提示用户通过企业微信联系江苏基地网络工程师（徐梁、王鸣、段承志）
- 关闭方式：点击"我知道了"按钮 / X按钮 / ESC键

### 3. 修改密码功能
在登录页添加"修改密码"入口，跳转到独立页面：
- 输入字段：账号、原密码、新密码、确认新密码
- 后端验证：账号存在性、原密码正确性、新密码规则
- 成功后跳转到登录页

## Technical Considerations

### 架构影响
- 新增 URL 路由：`/change-password/`
- 新增视图函数：`password_change` 在 `frontend_views.py`
- 新增模板：`templates/ipam/password_change.html`
- 修改现有模板：`templates/registration/login.html`

### 安全考虑
- CSRF Token 保护
- 原密码验证防止未授权修改
- 统一错误提示（"账号或原密码错误"）避免账号枚举
- 使用 Django 内置密码验证器
- 记录操作到审计日志

### 依赖
- Django 内置：`PasswordChangeForm`, `update_session_auth_hash`
- 前端：Alpine.js（已有）、Tailwind CSS（已有）

## Acceptance Criteria

### Feature 1: 删除底部链接
- [ ] 登录页不再显示"隐私政策"和"帮助中心"链接
- [ ] 页面布局保持美观

### Feature 2: 忘记密码弹窗
- [ ] 点击"忘记密码"显示模态弹窗
- [ ] 弹窗显示联系人：徐梁、王鸣、段承志
- [ ] 提示通过企业微信联系
- [ ] 支持手动关闭（X按钮、ESC键、"我知道了"按钮）
- [ ] 移动端适配正常

### Feature 3: 修改密码功能
- [ ] 登录页显示"修改密码"链接入口
- [ ] 修改密码页面包含：账号、原密码、新密码、确认密码字段
- [ ] 密码字段支持显示/隐藏切换
- [ ] 前端实时验证两次密码一致性
- [ ] 后端验证原密码正确性
- [ ] 密码修改成功后跳转登录页
- [ ] 记录审计日志

## Success Metrics

- 用户能够通过弹窗了解密码重置途径
- 用户能够自助完成密码修改
- 无安全漏洞（暴力破解、CSRF等）

## Dependencies & Risks

| 依赖/风险 | 影响 | 缓解措施 |
|----------|------|---------|
| Django 认证系统 | 低 | 使用内置组件 |
| Alpine.js 弹窗 | 低 | 项目已使用 |
| 审计日志系统 | 低 | 复用现有 AuditLog 模型 |

## Implementation Plan

### Phase 1: 删除底部链接 + 忘记密码弹窗

**修改文件**: `templates/registration/login.html`

```html
<!-- 删除: 底部链接区域 -->
<!-- 约在文件末尾，找到包含"隐私政策"和"帮助中心"的部分删除 -->

<!-- 添加: 忘记密码弹窗 -->
<div x-data="{ showForgotPassword: false }">
    <!-- 触发链接 -->
    <a href="#" @click.prevent="showForgotPassword = true"
       class="text-sm text-blue-600 hover:text-blue-500">
        忘记密码？
    </a>

    <!-- 模态弹窗 -->
    <div x-show="showForgotPassword"
         x-cloak
         class="fixed inset-0 z-50 overflow-y-auto"
         @keydown.escape.window="showForgotPassword = false">
        <!-- 遮罩层 -->
        <div class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm"
             @click="showForgotPassword = false"></div>

        <!-- 弹窗内容 -->
        <div class="flex min-h-screen items-center justify-center p-4">
            <div class="relative w-full max-w-sm bg-white dark:bg-slate-800
                        rounded-2xl shadow-2xl p-6">
                <!-- 关闭按钮 -->
                <button @click="showForgotPassword = false"
                        class="absolute right-4 top-4 text-slate-400 hover:text-slate-600">
                    <span class="material-symbols-outlined">close</span>
                </button>

                <!-- 图标 -->
                <div class="flex justify-center mb-4">
                    <div class="w-12 h-12 bg-amber-100 dark:bg-amber-500/20
                                rounded-full flex items-center justify-center">
                        <span class="material-symbols-outlined text-2xl text-amber-600">
                            help
                        </span>
                    </div>
                </div>

                <!-- 标题 -->
                <h3 class="text-lg font-semibold text-center text-slate-900 dark:text-white mb-2">
                    忘记密码？
                </h3>

                <!-- 内容 -->
                <p class="text-sm text-slate-600 dark:text-slate-400 text-center mb-4">
                    请通过企业微信联系江苏基地网络工程师重置密码：
                </p>

                <!-- 联系人列表 -->
                <div class="bg-slate-50 dark:bg-slate-900/50 rounded-lg p-4 mb-4">
                    <div class="flex items-center justify-center gap-4 text-sm font-medium text-slate-700 dark:text-slate-300">
                        <span>徐梁</span>
                        <span class="text-slate-300 dark:text-slate-600">|</span>
                        <span>王鸣</span>
                        <span class="text-slate-300 dark:text-slate-600">|</span>
                        <span>段承志</span>
                    </div>
                </div>

                <!-- 确认按钮 -->
                <button @click="showForgotPassword = false"
                        class="w-full py-2.5 bg-blue-600 hover:bg-blue-500
                               text-white font-medium rounded-lg transition-colors">
                    我知道了
                </button>
            </div>
        </div>
    </div>
</div>
```

### Phase 2: 添加修改密码入口

**修改文件**: `templates/registration/login.html`

```html
<!-- 在登录表单下方添加修改密码链接 -->
<div class="text-center mt-4">
    <a href="{% url 'ipam:password_change' %}"
       class="text-sm text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300">
        <span class="material-symbols-outlined text-sm align-middle">lock_reset</span>
        修改密码
    </a>
</div>
```

### Phase 3: 创建修改密码视图

**修改文件**: `ipam/frontend_views.py`

```python
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User

def password_change(request):
    """用户自助修改密码（无需登录）"""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        old_password = request.POST.get("old_password", "")
        new_password1 = request.POST.get("new_password1", "")
        new_password2 = request.POST.get("new_password2", "")

        # 验证两次密码一致
        if new_password1 != new_password2:
            messages.error(request, "两次输入的新密码不一致")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 验证新密码长度
        if len(new_password1) < 8:
            messages.error(request, "新密码长度至少8位")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 验证账号和原密码
        try:
            user = User.objects.get(username=username)
            if not user.check_password(old_password):
                messages.error(request, "账号或原密码错误")
                return render(request, "ipam/password_change.html", {
                    "form_data": {"username": username}
                })
        except User.DoesNotExist:
            messages.error(request, "账号或原密码错误")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 修改密码
        try:
            user.set_password(new_password1)
            user.save()

            # 记录审计日志
            AuditLog.objects.create(
                action="password_change",
                ip_address=request.POST.get("ip_address"),
                details=f"用户 {username} 修改了密码",
                changes={"action": "self_password_change"}
            )

            messages.success(request, "密码修改成功，请使用新密码登录")
            return redirect("login")
        except Exception as e:
            messages.error(request, f"密码修改失败: {e}")

    return render(request, "ipam/password_change.html")
```

### Phase 4: 创建修改密码模板

**新建文件**: `templates/ipam/password_change.html`

```html
{% extends 'base_auth.html' %}
{% load static %}

{% block title %}修改密码{% endblock %}

{% block content %}
<div class="w-full max-w-md" x-data="{
    showOldPassword: false,
    showNewPassword: false,
    password1: '',
    password2: '',
    get passwordsMatch() {
        return this.password1 === this.password2 || this.password2.length === 0;
    }
}">
    <div class="rounded-2xl border overflow-hidden shadow-2xl transition-colors
                bg-white/80 border-slate-200/50 backdrop-blur
                dark:bg-slate-800/50 dark:border-slate-700/50">

        <!-- 头部 -->
        <div class="px-8 py-6 border-b border-slate-200 dark:border-slate-700">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-blue-100 dark:bg-blue-600/20 rounded-lg
                            flex items-center justify-center">
                    <span class="material-symbols-outlined text-blue-600 dark:text-blue-400">
                        lock_reset
                    </span>
                </div>
                <div>
                    <h1 class="text-xl font-bold text-slate-900 dark:text-white">
                        修改密码
                    </h1>
                    <p class="text-sm text-slate-500 dark:text-slate-400">
                        请输入账号和密码信息
                    </p>
                </div>
            </div>
        </div>

        <!-- 表单 -->
        <form method="post" class="px-8 py-6 space-y-5">
            {% csrf_token %}

            <!-- 错误提示 -->
            {% if messages %}
            {% for message in messages %}
            <div class="p-4 rounded-lg text-sm flex items-center gap-2
                        {% if message.tags == 'error' %}
                        bg-red-100 text-red-600 dark:bg-red-500/10 dark:text-red-400
                        {% else %}
                        bg-green-100 text-green-600 dark:bg-green-500/10 dark:text-green-400
                        {% endif %}">
                <span class="material-symbols-outlined text-lg">
                    {% if message.tags == 'error' %}error{% else %}check_circle{% endif %}
                </span>
                {{ message }}
            </div>
            {% endfor %}
            {% endif %}

            <!-- 账号 -->
            <div>
                <label class="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    账号 <span class="text-red-500">*</span>
                </label>
                <div class="relative">
                    <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2
                                 text-xl text-slate-400">person</span>
                    <input type="text" name="username" required
                           value="{{ form_data.username|default:'' }}"
                           placeholder="请输入员工 ID"
                           class="w-full pl-11 pr-4 py-3 rounded-xl text-sm transition-all
                                  focus:outline-none focus:ring-2 focus:ring-blue-500
                                  bg-slate-100 border border-slate-200 text-slate-900
                                  dark:bg-slate-900/50 dark:border-slate-700 dark:text-white">
                </div>
            </div>

            <!-- 原密码 -->
            <div>
                <label class="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    原密码 <span class="text-red-500">*</span>
                </label>
                <div class="relative">
                    <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2
                                 text-xl text-slate-400">lock</span>
                    <input :type="showOldPassword ? 'text' : 'password'"
                           name="old_password" required
                           placeholder="请输入原密码"
                           class="w-full pl-11 pr-12 py-3 rounded-xl text-sm transition-all
                                  focus:outline-none focus:ring-2 focus:ring-blue-500
                                  bg-slate-100 border border-slate-200 text-slate-900
                                  dark:bg-slate-900/50 dark:border-slate-700 dark:text-white">
                    <button type="button" @click="showOldPassword = !showOldPassword"
                            class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400
                                   hover:text-slate-600 transition-colors">
                        <span class="material-symbols-outlined text-xl"
                              x-text="showOldPassword ? 'visibility_off' : 'visibility'"></span>
                    </button>
                </div>
            </div>

            <!-- 新密码 -->
            <div>
                <label class="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    新密码 <span class="text-red-500">*</span>
                </label>
                <div class="relative">
                    <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2
                                 text-xl text-slate-400">lock_reset</span>
                    <input :type="showNewPassword ? 'text' : 'password'"
                           name="new_password1" required
                           x-model="password1"
                           placeholder="请输入新密码（至少8位）"
                           class="w-full pl-11 pr-12 py-3 rounded-xl text-sm transition-all
                                  focus:outline-none focus:ring-2 focus:ring-blue-500
                                  bg-slate-100 border border-slate-200 text-slate-900
                                  dark:bg-slate-900/50 dark:border-slate-700 dark:text-white">
                    <button type="button" @click="showNewPassword = !showNewPassword"
                            class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400
                                   hover:text-slate-600 transition-colors">
                        <span class="material-symbols-outlined text-xl"
                              x-text="showNewPassword ? 'visibility_off' : 'visibility'"></span>
                    </button>
                </div>
                <p class="mt-1 text-xs text-slate-400">密码长度至少8位</p>
            </div>

            <!-- 确认新密码 -->
            <div>
                <label class="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    确认新密码 <span class="text-red-500">*</span>
                </label>
                <div class="relative">
                    <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2
                                 text-xl text-slate-400">lock_reset</span>
                    <input :type="showNewPassword ? 'text' : 'password'"
                           name="new_password2" required
                           x-model="password2"
                           placeholder="请再次输入新密码"
                           class="w-full pl-11 pr-4 py-3 rounded-xl text-sm transition-all
                                  focus:outline-none focus:ring-2 focus:ring-blue-500
                                  bg-slate-100 border border-slate-200 text-slate-900
                                  dark:bg-slate-900/50 dark:border-slate-700 dark:text-white"
                           :class="!passwordsMatch ? 'ring-2 ring-red-500 border-red-500' : ''">
                </div>
                <p x-show="!passwordsMatch" class="mt-1 text-xs text-red-500">
                    两次输入的密码不一致
                </p>
            </div>

            <!-- 按钮 -->
            <div class="flex gap-3 pt-2">
                <a href="{% url 'login' %}"
                   class="flex-1 py-3 text-center text-sm font-medium text-slate-600
                          hover:text-slate-900 bg-slate-100 hover:bg-slate-200
                          dark:text-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600
                          rounded-xl transition-colors">
                    返回登录
                </a>
                <button type="submit"
                        :disabled="!passwordsMatch"
                        :class="!passwordsMatch ? 'opacity-50 cursor-not-allowed' : ''"
                        class="flex-1 py-3 text-sm font-medium text-white
                               bg-blue-600 hover:bg-blue-500 rounded-xl transition-colors">
                    确认修改
                </button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

### Phase 5: 添加 URL 路由

**修改文件**: `ipam/urls.py`

```python
# 在 urlpatterns 中添加
path("password-change/", frontend_views.password_change, name="password_change"),
```

## Files to Modify

| 文件 | 操作 | 说明 |
|-----|------|------|
| `templates/registration/login.html` | 修改 | 删除底部链接、添加弹窗、添加修改密码入口 |
| `templates/ipam/password_change.html` | 新建 | 修改密码表单页面 |
| `ipam/frontend_views.py` | 修改 | 添加 password_change 视图函数 |
| `ipam/urls.py` | 修改 | 添加 password-change 路由 |

## Testing Checklist

### 手动测试
- [ ] 登录页底部链接已删除
- [ ] 点击"忘记密码"显示弹窗
- [ ] 弹窗显示正确的联系人信息
- [ ] 弹窗可通过X按钮/ESC键/"我知道了"按钮关闭
- [ ] 点击"修改密码"跳转到修改密码页面
- [ ] 输入错误账号/密码显示错误提示
- [ ] 两次密码不一致时显示提示且无法提交
- [ ] 密码修改成功后跳转登录页
- [ ] 移动端页面正常显示

### 安全测试
- [ ] CSRF Token 验证正常
- [ ] 无法绕过原密码验证
- [ ] 错误提示不泄露账号是否存在

## References & Research

### Internal References
- 登录模板: `/opt/ipim/backend/templates/registration/login.html`
- 认证配置: `/opt/ipim/backend/ipam_project/settings.py:244-246`
- 用户视图: `/opt/ipim/backend/ipam/frontend_views.py:703-820`

### External References
- [Django 密码管理](https://docs.djangoproject.com/en/4.2/topics/auth/passwords/)
- [Alpine.js 模态框](https://alpinejs.dev/directives/show)
- [OWASP 认证最佳实践](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
