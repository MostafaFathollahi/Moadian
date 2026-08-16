using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for invoice operations
/// </summary>
public interface IInvoiceService
{
    /// <summary>
    /// Sends invoices to the tax administration
    /// </summary>
    Task<List<InvoiceResponseDto>> SendInvoicesAsync(List<InvoiceDto> invoices, CancellationToken cancellationToken = default);

    /// <summary>
    /// Gets invoice status by tax IDs
    /// </summary>
    Task<List<InvoiceStatusDto>> GetInvoiceStatusAsync(List<string> taxIds, CancellationToken cancellationToken = default);
}

