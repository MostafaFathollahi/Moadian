using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Sdk.Configuration;
using TaxCollectData.Library.Sdk.Extensions;
using Microsoft.Extensions.DependencyInjection;

namespace TaxCollectData.Library.Sdk.Public;

/// <summary>
/// Main entry point for Tax SDK
/// </summary>
public class TaxSdk
{
    private readonly IInvoiceService _invoiceService;
    private readonly IInquiryService _inquiryService;
    private readonly ITaxpayerService _taxpayerService;
    private readonly IPaymentService _paymentService;

    public TaxSdk(
        IInvoiceService invoiceService,
        IInquiryService inquiryService,
        ITaxpayerService taxpayerService,
        IPaymentService paymentService)
    {
        _invoiceService = invoiceService ?? throw new ArgumentNullException(nameof(invoiceService));
        _inquiryService = inquiryService ?? throw new ArgumentNullException(nameof(inquiryService));
        _taxpayerService = taxpayerService ?? throw new ArgumentNullException(nameof(taxpayerService));
        _paymentService = paymentService ?? throw new ArgumentNullException(nameof(paymentService));
    }

    /// <summary>
    /// Configures and creates a new Tax SDK instance
    /// </summary>
    public static TaxSdk Configure(Action<TaxSdkOptions> configure)
    {
        var options = new TaxSdkOptions();
        configure(options);
        options.Validate();

        var services = new ServiceCollection();
        services.AddTaxSdk(options);
        var serviceProvider = services.BuildServiceProvider();

        return serviceProvider.GetRequiredService<TaxSdk>();
    }

    /// <summary>
    /// Sends invoices to the tax administration
    /// </summary>
    public async Task<List<InvoiceResponseDto>> SendInvoicesAsync(List<InvoiceDto> invoices, CancellationToken cancellationToken = default)
    {
        return await _invoiceService.SendInvoicesAsync(invoices, cancellationToken);
    }

    /// <summary>
    /// Gets invoice status by tax IDs
    /// </summary>
    public async Task<List<InvoiceStatusDto>> GetInvoiceStatusAsync(List<string> taxIds, CancellationToken cancellationToken = default)
    {
        return await _invoiceService.GetInvoiceStatusAsync(taxIds, cancellationToken);
    }

    /// <summary>
    /// Inquires invoices by time range
    /// </summary>
    public async Task<List<InquiryResultDto>> InquiryByTimeAsync(InquiryByTimeRangeDto dto, CancellationToken cancellationToken = default)
    {
        return await _inquiryService.InquiryByTimeAsync(dto, cancellationToken);
    }

    /// <summary>
    /// Inquires invoices by UID
    /// </summary>
    public async Task<List<InquiryResultDto>> InquiryByUidAsync(InquiryByUidDto dto, CancellationToken cancellationToken = default)
    {
        return await _inquiryService.InquiryByUidAsync(dto, cancellationToken);
    }

    /// <summary>
    /// Inquires invoices by reference number
    /// </summary>
    public async Task<List<InquiryResultDto>> InquiryByReferenceIdAsync(InquiryByReferenceNumberDto dto, CancellationToken cancellationToken = default)
    {
        return await _inquiryService.InquiryByReferenceIdAsync(dto, cancellationToken);
    }

    /// <summary>
    /// Gets taxpayer information by economic code
    /// </summary>
    public async Task<TaxpayerDto> GetTaxpayerAsync(string economicCode, CancellationToken cancellationToken = default)
    {
        return await _taxpayerService.GetTaxpayerAsync(economicCode, cancellationToken);
    }

    /// <summary>
    /// Registers a payment request
    /// </summary>
    public async Task<RegisterPaymentResultDto> RegisterPaymentAsync(RegisterPaymentRequestDto request, CancellationToken cancellationToken = default)
    {
        return await _paymentService.RegisterPaymentAsync(request, cancellationToken);
    }
}

