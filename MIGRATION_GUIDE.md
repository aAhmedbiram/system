# 📦 دليل نقل البيانات من Neon Gym إلى قاعدة البيانات الجديدة

## 📋 المتطلبات

1. ✅ تأكد من إنشاء الجداول في قاعدة البيانات الجديدة (شغّل `init_db.py` أولاً)
2. ✅ احصل على connection string من قاعدة البيانات القديمة (Neon Gym)
3. ✅ لديك connection string من قاعدة البيانات الجديدة

## 🔧 الخطوات

### الخطوة 1: الحصول على Connection String من قاعدة البيانات القديمة

#### من pgAdmin:
1. افتح pgAdmin
2. اتصل بـ Neon Gym database
3. اضغط كليك يمين على Database → Properties
4. اذهب إلى Connection tab
5. استخدم المعلومات لبناء connection string:
   ```
   postgresql://username:password@host:port/database?sslmode=require
   ```

#### من Neon Console:
1. اذهب إلى [Neon Console](https://console.neon.tech)
2. اختر Project الخاص بـ Neon Gym
3. اضغط على **"Connect"** أو **"Connection Details"**
4. انسخ connection string

### الخطوة 2: تحديث ملف Migration Script

افتح ملف `migrate_to_new_neon.py` وحدّث:

```python
# Old Database (Neon Gym)
OLD_DB_CONNECTION_STRING = 'postgresql://username:password@host:port/database?sslmode=require'

# New Database (Already set with your provided details)
NEW_DB_CONNECTION_STRING = 'postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require'
```

**أو** استخدم environment variables:
```bash
# Windows PowerShell
$env:OLD_DATABASE_URL="postgresql://user:pass@host:port/db?sslmode=require"
$env:NEW_DATABASE_URL="postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"

# Linux/Mac
export OLD_DATABASE_URL="postgresql://user:pass@host:port/db?sslmode=require"
export NEW_DATABASE_URL="postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"
```

### الخطوة 3: إنشاء الجداول في قاعدة البيانات الجديدة

قبل تشغيل migration، تأكد من إنشاء الجداول:

```bash
# Set the new database URL temporarily
$env:DATABASE_URL="postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"

# Run init_db.py
python system_app/init_db.py
```

### الخطوة 4: تشغيل Migration Script

```bash
python migrate_to_new_neon.py
```

سيقوم السكريبت بـ:
1. ✅ الاتصال بقاعدة البيانات القديمة والجديدة
2. ✅ نسخ جميع الجداول بالترتيب الصحيح (مع مراعاة Foreign Keys)
3. ✅ الحفاظ على IDs الأصلية
4. ✅ إعادة تعيين Sequences
5. ✅ عرض تقرير مفصل

### الخطوة 5: تحديث DATABASE_URL في التطبيق

بعد نجاح Migration، حدّث `DATABASE_URL` في:

#### Railway:
1. اذهب إلى Railway Dashboard
2. اختر Project
3. اضغط على **Variables**
4. حدّث `DATABASE_URL` إلى:
   ```
   postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require
   ```

#### Local Development:
```bash
# Windows PowerShell
$env:DATABASE_URL="postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"

# Linux/Mac
export DATABASE_URL="postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"
```

## 📊 الجداول التي سيتم نقلها

السكريبت سينقل جميع الجداول التالية بالترتيب الصحيح:

1. `users` - المستخدمين
2. `members` - الأعضاء
3. `supplements` - المكملات الغذائية
4. `staff` - الموظفين
5. `training_templates` - قوالب التدريب
6. `attendance_backup` - نسخة احتياطية للحضور
7. `attendance` - الحضور
8. `member_logs` - سجلات تعديل الأعضاء
9. `action_logs` - سجلات الإجراءات
10. `invitations` - الدعوات
11. `renewal_logs` - سجلات التجديد
12. `invoices` - الفواتير
13. `member_training_plans` - خطط التدريب للأعضاء
14. `pending_member_edits` - التعديلات المعلقة
15. `progress_tracking` - متابعة التقدم
16. `supplement_sales` - مبيعات المكملات
17. `staff_purchases` - مشتريات الموظفين

## ⚠️ تحذيرات مهمة

1. **Backup**: تأكد من عمل backup قبل البدء
2. **Test First**: جرب على قاعدة بيانات تجريبية أولاً إن أمكن
3. **No Duplicates**: السكريبت يستخدم `ON CONFLICT DO NOTHING` لتجنب التكرار
4. **Sequences**: Sequences سيتم إعادة تعيينها تلقائياً بعد النسخ

## 🔍 التحقق من النجاح

بعد Migration، تحقق من:

1. عدد السجلات في كل جدول
2. البيانات الأساسية (الأعضاء، المستخدمين)
3. العلاقات بين الجداول (Foreign Keys)
4. تسجيل الدخول للتطبيق

## 🆘 حل المشاكل

### خطأ: "Connection refused"
- تحقق من connection string
- تأكد من أن قاعدة البيانات نشطة
- تحقق من SSL mode

### خطأ: "Table does not exist"
- شغّل `init_db.py` أولاً لإنشاء الجداول

### خطأ: "Foreign key violation"
- السكريبت ينقل الجداول بالترتيب الصحيح
- إذا حدث خطأ، تحقق من البيانات في الجدول المذكور

### خطأ: "Duplicate key"
- السكريبت يتخطى السجلات المكررة تلقائياً
- هذا طبيعي إذا تم تشغيل Migration أكثر من مرة

## 📞 الدعم

إذا واجهت أي مشاكل، تحقق من:
1. Logs في console
2. Connection strings صحيحة
3. الجداول موجودة في قاعدة البيانات الجديدة

---

**ملاحظة**: بعد Migration الناجح، يمكنك حذف قاعدة البيانات القديمة إذا لم تعد تحتاجها.

