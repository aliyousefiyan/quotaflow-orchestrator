# پل ایمیل GitHub Actions: دو حساب Gmail و Yahoo آخر

این ماژول نیاز به راه‌اندازی یک‌باره توسط **مالک Gmail** دارد. از داخل همین گفتگو اجازه OAuth برای Gmail نداریم و برنامه را بدون نصب/مجوز کاربر فعال نمی‌کنیم.

## جریان
1. Google Apps Script هر ۱۵ دقیقه ایمیل‌های بالقوه GitHub را در **یک Gmail مشترک برای دو حساب** بررسی می‌کند.
2. فقط پیام‌های با فرستنده دامنه github.com، امضای معتبر DKIM مرتبط با GitHub، محصول **GitHub Actions**، آستانه روشن ۷۵/۸۵/۹۰/۱۰۰ و **نام دقیقاً یک حساب** پذیرفته می‌شوند. پیام‌های نامشخص/فورواردشده برای بررسی دستی کنار گذاشته می‌شوند.
3. در حالت واقعی پیام **فقط با شناسه مستعار حساب، درصد هشدار، زمان، شناسه هش‌شده و امضای HMAC** به **Issue خصوصی GitHub** ارسال می‌شود؛ ایمیل، متن پیام و اطلاعات مالی شخصی ارسال نمی‌شود.
4. کنترل‌کننده پیام‌های همان Issue را فقط‌خواندنی دریافت کرده و امضای HMAC را بررسی می‌کند. ۷۵٪ به معنی اخطار، و **۸۵٪ به بالا به معنی HOLD** است. این HOLD تا تأیید دستی بودجه جدید باقی می‌ماند.
5. کار جدید به حساب Gmail دوم با بودجه تأییدشده منتقل می‌شود. **Yahoo آخرین گزینه** و فقط با بودجه و مجوز مستقل است. کارهای درحال‌اجرا به خاطر اخطار متوقف نمی‌شوند.

## راه‌اندازی یک‌باره Gmail
1. از حساب Gmail مشترک به [script.google.com](https://script.google.com/) بروید و **New project** بسازید.
2. کد [Code.gs](Code.gs) را قرار دهید. در **Project Settings → Script Properties** این مقادیر را به‌صورت خصوصی وارد کنید:
   - `QF_OWNER_MAP_JSON`: برای دو حساب مجاز، نمونه `{"github-owner-one":"owner_a","github-owner-two":"owner_b"}`
   - `QF_PRIVATE_REPO`: مخزن خصوصی محل ثبت هشدارها؛ **نه مخزن عمومی QuotaFlow**
   - `QF_ISSUE_NUMBER`: شماره Issue خصوصی اختصاصی هشدارهای سهمیه
   - `QF_ISSUES_PAT`: توکن Fine-grained محدود به همان مخزن خصوصی با **Issues: Read and write** و تاریخ انقضای کوتاه. این توکن **توکن اجرای Actions نیست**.
   - `QF_HMAC_SECRET`: رمز تصادفی طولانی (حداقل ۳۲ کاراکتر) و یکسان با Secret خصوصی کنترل‌کننده `QF_ALERT_HMAC_SECRET`.
   - `QF_DRY_RUN`: ابتدا `true`.
3. تابع `pollGitHubQuotaAlerts` را **در حالت آزمایشی** اجرا و بخش Executions را بررسی کنید. **چون نسخه آزمایشی پیام را ارسال نمی‌کند، هیچ وضعیت حسابی عوض نمی‌شود.** اگر ایمیل واقعی با شناسه یکتا دیده نشد، نگاشت/Authenticity را بررسی کنید؛ قانون را حدسی شل نکنید.
4. با تأیید شخصی و مشاهده نمونه معتبر، مقدار `QF_DRY_RUN=false` را تنظیم و `installQuotaFlowMonitor` را یک بار اجرا کنید تا Trigger هر ۱۵ دقیقه ایجاد شود.
5. پیش از استفاده عملی، وجود اولین پیام واقعی HMAC معتبر در Issue خصوصی و خروجی `alerts-sync-issue` را بررسی کنید.
6. اگر سهمیه حساب‌ها بازنشانی شد، ایمیل جدید به تنهایی **مجوز حذف HOLD** نیست؛ باید بودجه واقعی جدید و زمان مشاهده آن تأیید شود.

## دستور کنترل‌کننده
در دستگاهی که `quotaflow` و `accounts.json` و `budgets.json` خصوصی دارد:

```bash
# کلیدهای زیر فقط باید در Secret Manager یا محیط خصوصی تنظیم شده باشند.
# QF_ALERT_HMAC_SECRET — HMAC shared secret
# QF_ISSUE_READ_TOKEN — fine-grained, Issues Read-only token for private issue
python -m quotaflow --config accounts.json --budgets budgets.json --routing routing.json --state .quotaflow/queue.sqlite3 alerts-sync-issue --issue-repo YOUR_PRIVATE_OWNER/YOUR_PRIVATE_REPO --issue-number YOUR_ISSUE
python -m quotaflow --config accounts.json --budgets budgets.json --routing routing.json --state .quotaflow/queue.sqlite3 alerts-status
python -m quotaflow --config accounts.json --budgets budgets.json --routing routing.json --state .quotaflow/queue.sqlite3 plan
```

**Yahoo:** اگر حساب سوم فقط صندوق Yahoo دارد، نیازی نیست ایمیل آن را به Gmail منتقل کنید تا **آخرین مقصد** باشد. اما بودجه و مجوز GitHub آن باید جداگانه تأیید شود. در صورت تمایل می‌توان فوروارد یک‌طرفه ایمیل‌های Yahoo را بعداً طراحی کرد، ولی بدون اعتبارسنجی مستقل، ایمیل فورواردشده ورودی تصمیم خودکار نیست.

پیش از هر نوبت برنامه‌ریزی مسیر خصوصی، دستور `alerts-sync-issue` باید حداکثر طی **۶۰ دقیقه اخیر** با موفقیت به Issue خصوصی دسترسی پیدا کرده باشد؛ در غیر این صورت انتخاب حساب خصوصی متوقف می‌شود. همگام‌سازی موفق با Issue به‌تنهایی اثبات نمی‌کند Trigger Gmail فعال است؛ صحت اجرای Apps Script نیز باید در حساب Google بررسی شود.

## محدودیت‌های صداقت/ایمنی
- **Apps Script و توکن‌ها در حساب شما هنوز نصب نشده‌اند.** این مخزن فقط کد و راهنمای آماده دارد.
- Email alert نسبت دقیق **موجودی قابل‌مصرف** را نشان نمی‌دهد؛ بودجه مقصد باید جداگانه از Billing خوانده شود.
- تشخیص ایمیل بر اساس نمونه واقعی ممکن است نیاز به اصلاح با **آزمون فقط‌خواندنی** داشته باشد؛ Gmail بعضی هدرها را در همه پیام‌ها ارائه نمی‌کند و در این حالت برنامه پیام را رد می‌کند.
- ارسال خودکار کار از این ابزار بدون صف، Controller معتبر، توکن مجاز و بودجه تازه مجاز نیست. گزینه `dispatch --approve-dispatch` همچنان جداگانه لازم است.
- هیچ دسترسی Work/Codex، سفارش معاملاتی، SSH یا داده خصوصی در پل ایمیل وجود ندارد.

مراجع: [GitHub Alerts](https://docs.github.com/en/billing/how-tos/set-up-budgets)، [Google GmailApp](https://developers.google.com/apps-script/reference/gmail/gmail-app)، [Time-driven triggers](https://developers.google.com/apps-script/guides/triggers/installable).
