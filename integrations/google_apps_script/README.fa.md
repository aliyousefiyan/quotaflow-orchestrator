# پل ایمیل GitHub Actions: دو حساب Gmail و Yahoo آخر

این ماژول نیاز به راه‌اندازی یک‌باره توسط **مالک Gmail** دارد. از داخل همین گفتگو اجازه OAuth برای Gmail نداریم و برنامه را بدون نصب/مجوز کاربر فعال نمی‌کنیم.

## جریان
1. Google Apps Script هر ۱۵ دقیقه ایمیل‌های بالقوه GitHub را در **یک Gmail مشترک برای دو حساب** بررسی می‌کند.
2. فقط پیام‌های با فرستنده دامنه github.com، امضای معتبر DKIM مرتبط با GitHub، محصول **GitHub Actions**، آستانه روشن ۷۵/۸۵/۹۰/۱۰۰ و **نام دقیقاً یک حساب** پذیرفته می‌شوند. پیام‌های نامشخص/فورواردشده برای بررسی دستی کنار گذاشته می‌شوند.
3. در حالت واقعی پیام **فقط با شناسه مستعار حساب، درصد هشدار، زمان، شناسه هش‌شده و امضای HMAC** به **Issue خصوصی GitHub** ارسال می‌شود؛ ایمیل، متن پیام و اطلاعات مالی شخصی ارسال نمی‌شود.
4. کنترل‌کننده پیام‌های همان Issue را فقط‌خواندنی دریافت کرده و امضای HMAC را بررسی می‌کند. ۷۵٪ به معنی اخطار، و **۸۵٪ به بالا به معنی HOLD** است. این HOLD تا تأیید دستی بودجه جدید باقی می‌ماند.
5. کار جدید به حساب Gmail دوم با بودجه تأییدشده منتقل می‌شود. **Yahoo آخرین گزینه** و فقط با بودجه و مجوز مستقل است. کارهای درحال‌اجرا به خاطر اخطار متوقف نمی‌شوند.

## نسخه امن Gmail Read-only — ضروری

این نسخه عمداً دیگر از `GmailApp` استفاده نمی‌کند. از API رسمی Gmail با مجوز **`gmail.readonly`** و توکن محدود به همان محدوده استفاده می‌کند؛ بنابراین برنامه حق ارسال، ویرایش یا حذف ایمیل ندارد.

**هر دو فایل باید در پروژه Google Apps Script جایگزین شوند:**

مانيفست جدید علاوه‌بر محدودکردن مجوزها، Gmail API را در سرویس‌های پیشرفته پروژه فعال می‌کند (برای پروژه پیش‌فرض Google Cloud) و اتصال خارجی را به آدرس‌های Gmail API و GitHub API محدود می‌کند. <https://developers.google.com/apps-script/guides/services/advanced>

1. در Editor، **تمام کد قبلی `Code.gs`** را حذف و [نسخه به‌روز `Code.gs`](Code.gs) را کامل جایگزین و Save کنید. هیچ تابع قدیمی `GmailApp` نباید در پروژه باقی بماند.
2. در **Project Settings** تیک `Show "appsscript.json" manifest file in editor` را فعال کنید.
3. فایل `appsscript.json` در Editor نمایش داده می‌شود؛ مقدار `oauthScopes` را دقیقاً برابر [manifest محدودشده](appsscript.json) تنظیم کنید (یا اگر تنظیمات دیگری ندارید کل فایل نمونه را جایگزین کنید):
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/script.external_request`
   - `https://www.googleapis.com/auth/script.scriptapp`
4. Save و Refresh کنید و دوباره `pollGitHubQuotaAlerts` را در حالت `QF_DRY_RUN=true` اجرا کنید. در صفحه OAuth باید «**خواندن ایمیل**»، «اتصال به سرویس بیرونی» و «اجرای برنامه بدون حضور شما» دیده شود، **نه** «Read, compose, send, and permanently delete all your email». اگر مجوز کامل Gmail همچنان ظاهر شد، **تأیید نکنید**؛ کدهای باقیمانده و `oauthScopes` را بررسی کنید.
5. اگر قبلاً مجوز گسترده را داده‌اید، از `Google Account → Security → Your connections to third-party apps & services` دسترسی قبلی همین پروژه را لغو کنید و سپس با نسخه جدید دوباره مجوز بدهید. لغو ممکن است اجرای Triggerهای قبلی را متوقف کند.

**نکته:** `gmail.readonly` همچنان از لحاظ خواندن، به پیام‌های صندوق Gmail دسترسی دارد و محدود به ایمیل‌های GitHub نیست؛ تنها *رفتار کد* جستجو را به پیام‌های مرتبط با GitHub محدود می‌کند. توکن ارسال/حذف ندارد. چون نیاز داریم صاحب دو حساب را از محتوای هشدار تشخیص بدهیم، دسترسی صرفاً به فراداده (`gmail.metadata`) کافی نیست.

**مرحله اول آزمایشی** فقط `QF_OWNER_MAP_JSON` و `QF_DRY_RUN=true` را در Script Properties لازم دارد. توکن GitHub، Issue و HMAC در Dry Run لازم نیست. قبل از صدور مجوزهای واقعی، کد و Manifest را هر دو تعویض کنید.

## راه‌اندازی یک‌باره Gmail
1. از حساب Gmail مشترک به [script.google.com](https://script.google.com/) بروید و **New project** بسازید.
2. هر دو فایل [Code.gs](Code.gs) و [appsscript.json](appsscript.json) را مطابق بخش بالا در همان پروژه تنظیم کنید. سپس در **Project Settings → Script Properties** این مقادیر را به‌صورت خصوصی وارد کنید:
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

مراجع: [GitHub Alerts](https://docs.github.com/en/billing/how-tos/set-up-budgets)، [Gmail API read-only](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)، [Time-driven triggers](https://developers.google.com/apps-script/guides/triggers/installable).
