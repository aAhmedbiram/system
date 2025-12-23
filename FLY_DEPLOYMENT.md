# 🚀 Fly.io Deployment Guide

## ✅ الملفات المطلوبة (تم إنشاؤها)

1. **fly.toml** - إعدادات Fly.io
2. **Dockerfile** - لبناء الصورة
3. **.dockerignore** - لتجاهل الملفات غير الضرورية

## 📋 الخطوات

### 1. تثبيت Fly CLI (إذا لم يكن مثبتاً)

```bash
# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex

# أو من خلال winget
winget install -e --id Fly.Flyctl
```

### 2. تسجيل الدخول إلى Fly.io

```bash
fly auth login
```

### 3. إعداد Environment Variables

```bash
# SECRET_KEY (مطلوب)
fly secrets set SECRET_KEY="your-secret-key-here"

# DATABASE_URL (قاعدة البيانات الجديدة)
fly secrets set DATABASE_URL="postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"

# GMAIL_APP_PASSWORD (إذا كنت تستخدمه)
fly secrets set GMAIL_APP_PASSWORD="your-gmail-app-password"

# BASE_URL (URL التطبيق على Fly.io)
fly secrets set BASE_URL="https://system-rival.fly.dev"
```

### 4. Deploy التطبيق

```bash
fly deploy
```

## 🔧 إعدادات fly.toml

- **Port**: 5000 (مطابق للتطبيق)
- **Region**: iad (يمكن تغييره)
- **Memory**: 512 MB
- **CPU**: 1 shared CPU

## ⚠️ ملاحظات مهمة

1. **DATABASE_URL**: تأكد من إضافة connection string لقاعدة البيانات الجديدة
2. **SECRET_KEY**: استخدم مفتاح قوي وآمن
3. **BASE_URL**: حدّثه بعد الحصول على URL النهائي من Fly.io

## 🐛 حل المشاكل

### إذا فشل الـ build:
```bash
# شاهد الـ logs
fly logs

# أو
fly logs --app system-rival
```

### إذا فشل الـ deploy:
```bash
# تحقق من الـ status
fly status

# أعد المحاولة
fly deploy
```

### إذا كان التطبيق لا يعمل:
```bash
# تحقق من الـ machines
fly machines list

# شاهد الـ logs
fly logs
```

## 📊 التحقق من الـ Deployment

بعد الـ deploy الناجح:
1. افتح: `https://system-rival.fly.dev`
2. تحقق من أن التطبيق يعمل
3. جرب تسجيل الدخول

---

**جاهز للـ deploy!** 🚀

