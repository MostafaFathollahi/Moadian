using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for inquiry operations
/// </summary>
public interface IInquiryService
{
    /// <summary>
    /// Inquires invoices by time range
    /// </summary>
    Task<List<InquiryResultDto>> InquiryByTimeAsync(InquiryByTimeRangeDto dto, CancellationToken cancellationToken = default);

    /// <summary>
    /// Inquires invoices by UID
    /// </summary>
    Task<List<InquiryResultDto>> InquiryByUidAsync(InquiryByUidDto dto, CancellationToken cancellationToken = default);

    /// <summary>
    /// Inquires invoices by reference number
    /// </summary>
    Task<List<InquiryResultDto>> InquiryByReferenceIdAsync(InquiryByReferenceNumberDto dto, CancellationToken cancellationToken = default);
}

