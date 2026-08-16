# Tax Collect Data SDK - .NET

[![.NET](https://img.shields.io/badge/.NET-8.0-blue.svg)](https://dotnet.microsoft.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

SDK رسمی .NET برای ارسال و مدیریت فاکتورهای الکترونیکی به سازمان امور مالیاتی ایران

## 📋 فهرست مطالب

- [ویژگی‌ها](#-ویژگیها)
- [نصب](#-نصب)
- [شروع سریع](#-شروع-سریع)
- [راه‌اندازی](#-راهاندازی)
- [مثال‌های استفاده](#-مثالهای-استفاده)
- [API Reference](#-api-reference)
- [مدیریت خطا](#-مدیریت-خطا)
- [بهترین روش‌ها](#-بهترین-روشها)
- [سوالات متداول](#-سوالات-متداول)

## ✨ ویژگی‌ها

- ✅ **Clean Architecture** - ساختار تمیز و قابل نگهداری
- ✅ **Dependency Injection** - پشتیبانی کامل از DI
- ✅ **Fluent API** - رابط کاربری ساده و روان
- ✅ **Async/Await** - پشتیبانی کامل از عملیات ناهمزمان
- ✅ **Testable** - قابل تست با Mock و Stub
- ✅ **Type-Safe** - نوع‌ایمن و بدون خطای زمان اجرا
- ✅ **Comprehensive Error Handling** - مدیریت خطای جامع
- ✅ **PKCS#8 & PKCS#11** - پشتیبانی از گواهینامه‌های نرم‌افزاری و سخت‌افزاری
- ✅ **Unit & Integration Tests** - تست‌های کامل

## 📦 نصب

### NuGet Package Manager

```bash
Install-Package TaxCollectData.Library
```

### .NET CLI

```bash
dotnet add package TaxCollectData.Library
```

### PackageReference

```xml
<PackageReference Include="TaxCollectData.Library" Version="2.0.22" />
```

## 🚀 شروع سریع

### مثال ساده: ارسال فاکتور

```csharp
using TaxCollectData.Library.Sdk.Public;
using TaxCollectData.Library.Application.DTOs;

// راه‌اندازی SDK
var sdk = TaxSdk.Configure(options =>
{
    options.BaseUrl = "https://api.tax.gov.ir";
    options.ClientId = "A111YO";
    options.PrivateKeyPath = @"C:\Certificates\privatekey.pem";
    options.CertificatePath = @"C:\Certificates\certificate.crt";
});

// ایجاد فاکتور
var invoice = new InvoiceDto
{
    Header = new HeaderDto
    {
        taxid = "TAX123456789012345678901234567890",
        indatim = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        ins = 1,
        inty = 1,
        inp = 1,
        tins = "14003778990",  // شناسه ملی فروشنده
        tinb = "10100302746",  // شناسه ملی خریدار
        tprdis = 100_000,      // مجموع قیمت قبل از تخفیف
        tdis = 5_000,          // مجموع تخفیف
        tadis = 95_000,        // مجموع قیمت بعد از تخفیف
        tvam = 8_550,          // مجموع مالیات بر ارزش افزوده
        todam = 0,             // سایر مالیات‌ها
        tbill = 103_550,       // مجموع کل فاکتور
        setm = 2               // روش تسویه
    },
    Body = new List<BodyItemDto>
    {
        new BodyItemDto
        {
            sstid = "2710000138624",  // کد کالا/خدمت
            sstt = "محصول نمونه",     // شرح کالا/خدمت
            mu = "164",               // واحد اندازه‌گیری
            am = 1,                   // تعداد/مقدار
            fee = 100_000,            // قیمت واحد
            prdis = 100_000,          // قیمت قبل از تخفیف
            dis = 5_000,              // تخفیف
            adis = 95_000,            // قیمت بعد از تخفیف
            vra = 9,                  // نرخ مالیات بر ارزش افزوده
            vam = 8_550,              // مالیات بر ارزش افزوده
            tsstam = 103_550          // مجموع قیمت کالا/خدمت
        }
    }
};

// ارسال فاکتور
var result = await sdk.SendInvoicesAsync(new List<InvoiceDto> { invoice });

// بررسی نتیجه
foreach (var response in result)
{
    Console.WriteLine($"Tax ID: {response.TaxId}");
    Console.WriteLine($"Reference Number: {response.ReferenceNumber}");
    Console.WriteLine($"UID: {response.Uid}");
    Console.WriteLine($"Status: {response.Data}");
}
```

## ⚙️ راه‌اندازی

### روش 1: Fluent API (ساده‌ترین روش)

```csharp
var sdk = TaxSdk.Configure(options =>
{
    options.BaseUrl = "https://api.tax.gov.ir";
    options.ClientId = "A111YO";
    options.PrivateKeyPath = "privatekey.pem";
    options.CertificatePath = "certificate.crt";
    options.RequestTimeout = TimeSpan.FromMinutes(10);
    options.ApiVersion = "v2";
});
```

### روش 2: Dependency Injection (توصیه می‌شود برای برنامه‌های بزرگ)

```csharp
using Microsoft.Extensions.DependencyInjection;
using TaxCollectData.Library.Sdk.Extensions;
using TaxCollectData.Library.Sdk.Configuration;

// در Startup.cs یا Program.cs
public void ConfigureServices(IServiceCollection services)
{
    var options = new TaxSdkOptions
    {
        BaseUrl = "https://api.tax.gov.ir",
        ClientId = "A111YO",
        PrivateKeyPath = "privatekey.pem",
        CertificatePath = "certificate.crt",
        RequestTimeout = TimeSpan.FromMinutes(10)
    };
    
    services.AddTaxSdk(options);
    
    // سایر سرویس‌ها...
}

// استفاده در Controller یا Service
public class InvoiceController : ControllerBase
{
    private readonly TaxSdk _taxSdk;
    
    public InvoiceController(TaxSdk taxSdk)
    {
        _taxSdk = taxSdk;
    }
    
    [HttpPost]
    public async Task<IActionResult> SendInvoice([FromBody] InvoiceDto invoice)
    {
        var result = await _taxSdk.SendInvoicesAsync(new List<InvoiceDto> { invoice });
        return Ok(result);
    }
}
```

### روش 3: Builder Pattern

```csharp
using TaxCollectData.Library.Sdk.Builders;

var options = new TaxSdkBuilder()
    .WithBaseUrl("https://api.tax.gov.ir")
    .WithClientId("A111YO")
    .WithPkcs8Certificate("privatekey.pem", "certificate.crt")
    .WithTimeout(TimeSpan.FromMinutes(10))
    .WithApiVersion("v2")
    .WithCustomHeader("X-Custom-Header", "value")
    .Build();

var services = new ServiceCollection();
services.AddTaxSdk(options);
var serviceProvider = services.BuildServiceProvider();
var sdk = serviceProvider.GetRequiredService<TaxSdk>();
```

### پیکربندی با PKCS#11 (گواهینامه سخت‌افزاری)

```csharp
var sdk = TaxSdk.Configure(options =>
{
    options.BaseUrl = "https://api.tax.gov.ir";
    options.ClientId = "A111YO";
    options.Pkcs11LibraryPath = @"C:\Path\To\Pkcs11.dll";
    options.Pkcs11TokenSerialNumber = "2da4b5e60001000d7ca6";
    options.Pkcs11TokenPin = "1234";
});
```

## 📚 مثال‌های استفاده

### 1. ارسال فاکتور

```csharp
// ایجاد فاکتور کامل
var invoice = new InvoiceDto
{
    Header = new HeaderDto
    {
        taxid = GenerateTaxId(),  // باید با الگوریتم Verhoeff تولید شود
        indatim = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        ins = 1,
        inty = 1,
        inp = 1,
        tins = "14003778990",
        tinb = "10100302746",
        tprdis = 200_000,
        tdis = 10_000,
        tadis = 190_000,
        tvam = 17_100,
        todam = 0,
        tbill = 207_100,
        setm = 2
    },
    Body = new List<BodyItemDto>
    {
        new BodyItemDto
        {
            sstid = "2710000138624",
            sstt = "کالای نمونه",
            mu = "164",
            am = 2,
            fee = 100_000,
            prdis = 200_000,
            dis = 10_000,
            adis = 190_000,
            vra = 9,
            vam = 17_100,
            tsstam = 207_100
        }
    },
    Payments = new List<PaymentItemDto>
    {
        new PaymentItemDto
        {
            iinn = "1234567890",
            acn = "9876543210",
            trmn = "TERM001",
            trn = "TRN001",
            pmt = 1,  // روش پرداخت: نقدی
            pv = 207_100
        }
    }
};

// ارسال
var result = await sdk.SendInvoicesAsync(new List<InvoiceDto> { invoice });
```

### 2. استعلام وضعیت فاکتور

```csharp
// استعلام با Tax ID
var taxIds = new List<string> { "TAX123...", "TAX456..." };
var statuses = await sdk.GetInvoiceStatusAsync(taxIds);

foreach (var status in statuses)
{
    Console.WriteLine($"Tax ID: {status.TaxId}");
    Console.WriteLine($"Invoice Status: {status.InvoiceStatus}");
    Console.WriteLine($"Article 6 Status: {status.Article6Status}");
    if (!string.IsNullOrEmpty(status.Error))
    {
        Console.WriteLine($"Error: {status.Error}");
    }
}
```

### 3. استعلام بر اساس بازه زمانی

```csharp
var inquiryDto = new InquiryByTimeRangeDto(
    start: DateTime.Now.AddDays(-7),
    end: DateTime.Now,
    pageable: new Pageable(pageNumber: 0, pageSize: 10),
    status: RequestStatus.SUCCESS
);

var results = await sdk.InquiryByTimeAsync(inquiryDto);

foreach (var result in results)
{
    Console.WriteLine($"Reference: {result.ReferenceNumber}");
    Console.WriteLine($"UID: {result.Uid}");
    Console.WriteLine($"Status: {result.Status}");
    
    if (result.Data.Success)
    {
        Console.WriteLine("✅ فاکتور با موفقیت ثبت شد");
    }
    else
    {
        Console.WriteLine("❌ خطا در ثبت فاکتور:");
        foreach (var error in result.Data.Error)
        {
            Console.WriteLine($"  - {error.Code}: {error.Message}");
        }
    }
}
```

### 4. استعلام بر اساس UID

```csharp
var inquiryDto = new InquiryByUidDto(
    uidList: new List<string> { "uid1", "uid2", "uid3" },
    fiscalId: "A111YO",
    start: DateTime.Now.AddDays(-30),
    end: DateTime.Now
);

var results = await sdk.InquiryByUidAsync(inquiryDto);
```

### 5. استعلام بر اساس شماره مرجع

```csharp
var inquiryDto = new InquiryByReferenceNumberDto(
    referenceNumbers: new List<string> { "REF001", "REF002" },
    start: DateTime.Now.AddDays(-7),
    end: DateTime.Now
);

var results = await sdk.InquiryByReferenceIdAsync(inquiryDto);
```

### 6. دریافت اطلاعات مودی مالیاتی

```csharp
var taxpayer = await sdk.GetTaxpayerAsync("14003778990");

Console.WriteLine($"نام/نام تجاری: {taxpayer.NameTrade}");
Console.WriteLine($"وضعیت: {taxpayer.TaxpayerStatus}");
Console.WriteLine($"نوع: {taxpayer.TaxpayerType}");
Console.WriteLine($"کد پستی: {taxpayer.PostalcodeTaxpayer}");
Console.WriteLine($"آدرس: {taxpayer.AddressTaxpayer}");
```

### 7. ثبت پرداخت

```csharp
var paymentRequest = new RegisterPaymentRequestDto
{
    TaxId = "TAX123456789012345678901234567890",
    PaidAmount = 207_100,
    PaymentDate = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
    PaymentMethod = PaymentMethod.Cash,  // یا Cheque, CreditCard, BankTransfer
    TerminalNumber = "TERM001",
    ReferenceNumber = "PAYREF001"
};

var result = await sdk.RegisterPaymentAsync(paymentRequest);

if (result.RequestStatus == RequestStatus.SUCCESS)
{
    Console.WriteLine("✅ پرداخت با موفقیت ثبت شد");
}
else
{
    Console.WriteLine("❌ خطا در ثبت پرداخت:");
    foreach (var error in result.Error)
    {
        Console.WriteLine($"  - {error.Code}: {error.Message}");
    }
}
```

### 8. استفاده با CancellationToken

```csharp
var cts = new CancellationTokenSource(TimeSpan.FromMinutes(5));

try
{
    var result = await sdk.SendInvoicesAsync(invoices, cts.Token);
    // پردازش نتیجه...
}
catch (OperationCanceledException)
{
    Console.WriteLine("عملیات لغو شد");
}
```

## 📖 API Reference

### TaxSdk Class

کلاس اصلی SDK که تمام عملیات را فراهم می‌کند.

#### Methods

##### `SendInvoicesAsync`
ارسال فاکتورها به سازمان امور مالیاتی

```csharp
Task<List<InvoiceResponseDto>> SendInvoicesAsync(
    List<InvoiceDto> invoices, 
    CancellationToken cancellationToken = default)
```

**Parameters:**
- `invoices`: لیست فاکتورها
- `cancellationToken`: توکن لغو عملیات

**Returns:**
- لیست پاسخ‌های ارسال فاکتور

##### `GetInvoiceStatusAsync`
دریافت وضعیت فاکتورها بر اساس Tax ID

```csharp
Task<List<InvoiceStatusDto>> GetInvoiceStatusAsync(
    List<string> taxIds, 
    CancellationToken cancellationToken = default)
```

##### `InquiryByTimeAsync`
استعلام فاکتورها بر اساس بازه زمانی

```csharp
Task<List<InquiryResultDto>> InquiryByTimeAsync(
    InquiryByTimeRangeDto dto, 
    CancellationToken cancellationToken = default)
```

##### `InquiryByUidAsync`
استعلام فاکتورها بر اساس UID

```csharp
Task<List<InquiryResultDto>> InquiryByUidAsync(
    InquiryByUidDto dto, 
    CancellationToken cancellationToken = default)
```

##### `InquiryByReferenceIdAsync`
استعلام فاکتورها بر اساس شماره مرجع

```csharp
Task<List<InquiryResultDto>> InquiryByReferenceIdAsync(
    InquiryByReferenceNumberDto dto, 
    CancellationToken cancellationToken = default)
```

##### `GetTaxpayerAsync`
دریافت اطلاعات مودی مالیاتی

```csharp
Task<TaxpayerDto> GetTaxpayerAsync(
    string economicCode, 
    CancellationToken cancellationToken = default)
```

##### `RegisterPaymentAsync`
ثبت پرداخت فاکتور

```csharp
Task<RegisterPaymentResultDto> RegisterPaymentAsync(
    RegisterPaymentRequestDto request, 
    CancellationToken cancellationToken = default)
```

## 🛡️ مدیریت خطا

SDK از Domain Exceptions استفاده می‌کند:

```csharp
try
{
    var result = await sdk.SendInvoicesAsync(invoices);
}
catch (TaxApiException ex)
{
    // خطای API
    Console.WriteLine($"خطای API: {ex.Message}");
    Console.WriteLine($"کد خطا: {ex.ErrorCode}");
    Console.WriteLine($"پیام خطا: {ex.ErrorMessage}");
    Console.WriteLine($"کد وضعیت HTTP: {ex.StatusCode}");
}
catch (CertificateException ex)
{
    // خطای گواهینامه
    Console.WriteLine($"خطای گواهینامه: {ex.Message}");
}
catch (CryptographyException ex)
{
    // خطای رمزنگاری
    Console.WriteLine($"خطای رمزنگاری: {ex.Message}");
}
catch (InvalidTaxIdException ex)
{
    // خطای Tax ID نامعتبر
    Console.WriteLine($"Tax ID نامعتبر: {ex.Message}");
}
catch (Exception ex)
{
    // سایر خطاها
    Console.WriteLine($"خطای غیرمنتظره: {ex.Message}");
}
```

## 💡 بهترین روش‌ها

### 1. استفاده از Dependency Injection

```csharp
// ✅ خوب
public class InvoiceService
{
    private readonly TaxSdk _taxSdk;
    
    public InvoiceService(TaxSdk taxSdk)
    {
        _taxSdk = taxSdk;
    }
}

// ❌ بد
public class InvoiceService
{
    private readonly TaxSdk _taxSdk = TaxSdk.Configure(/* ... */);
}
```

### 2. مدیریت خطا

```csharp
// ✅ خوب
try
{
    var result = await _taxSdk.SendInvoicesAsync(invoices);
    // پردازش موفق
}
catch (TaxApiException ex) when (ex.StatusCode == 429)
{
    // Retry logic
    await Task.Delay(1000);
    return await _taxSdk.SendInvoicesAsync(invoices);
}

// ❌ بد
var result = await _taxSdk.SendInvoicesAsync(invoices); // بدون try-catch
```

### 3. استفاده از CancellationToken

```csharp
// ✅ خوب
public async Task ProcessInvoicesAsync(CancellationToken cancellationToken)
{
    var result = await _taxSdk.SendInvoicesAsync(
        invoices, 
        cancellationToken);
}

// ❌ بد
public async Task ProcessInvoicesAsync()
{
    var result = await _taxSdk.SendInvoicesAsync(invoices); // بدون CancellationToken
}
```

### 4. تولید Tax ID

```csharp
// استفاده از TaxIdProvider برای تولید Tax ID معتبر
using TaxCollectData.Library.Domain.Interfaces;
using TaxCollectData.Library.Infrastructure.Algorithms;
using TaxCollectData.Library.Infrastructure.Providers;

var algorithm = new VerhoeffAlgorithm();
var taxIdProvider = new TaxIdProvider(algorithm);

var serial = 123456789L;
var date = DateTime.Now;
var taxId = taxIdProvider.GenerateTaxId("A111YO", serial, date);
```

### 5. Configuration از appsettings.json

```json
{
  "TaxSdk": {
    "BaseUrl": "https://api.tax.gov.ir",
    "ClientId": "A111YO",
    "PrivateKeyPath": "certificates/privatekey.pem",
    "CertificatePath": "certificates/certificate.crt",
    "RequestTimeout": "00:10:00",
    "ApiVersion": "v2"
  }
}
```

```csharp
// در Startup.cs
var taxSdkConfig = Configuration.GetSection("TaxSdk");
var options = new TaxSdkOptions();
taxSdkConfig.Bind(options);
services.AddTaxSdk(options);
```

## ❓ سوالات متداول

### چگونه Tax ID تولید کنم؟

```csharp
var algorithm = new VerhoeffAlgorithm();
var taxIdProvider = new TaxIdProvider(algorithm);
var taxId = taxIdProvider.GenerateTaxId(clientId, serial, date);
```

### آیا می‌توانم از گواهینامه سخت‌افزاری استفاده کنم؟

بله، با استفاده از PKCS#11:

```csharp
options.Pkcs11LibraryPath = "path/to/pkcs11.dll";
options.Pkcs11TokenSerialNumber = "serial";
options.Pkcs11TokenPin = "pin";
```

### چگونه خطاها را مدیریت کنم؟

از try-catch با Domain Exceptions استفاده کنید:

```csharp
try { /* ... */ }
catch (TaxApiException ex) { /* ... */ }
catch (CertificateException ex) { /* ... */ }
```

### آیا می‌توانم از چندین instance از SDK استفاده کنم؟

بله، هر instance مستقل است و می‌توانید چندین instance با تنظیمات مختلف ایجاد کنید.

### چگونه timeout را تنظیم کنم؟

```csharp
options.RequestTimeout = TimeSpan.FromMinutes(15);
```

## 📝 License

این پروژه تحت مجوز MIT منتشر شده است.

## 🤝 مشارکت

مشارکت‌ها خوش‌آمد هستند! لطفاً ابتدا یک Issue ایجاد کنید.

## 📞 پشتیبانی

برای سوالات و پشتیبانی:
- ایجاد Issue در GitHub
- ایمیل: support@example.com

---

**نکته:** این SDK بر اساس Clean Architecture طراحی شده و کاملاً قابل تست است. برای اطلاعات بیشتر به مستندات مراجعه کنید.

