using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.ExternalApi;

namespace TaxCollectData.Library.Application.Services;

/// <summary>
/// Service for inquiry operations
/// </summary>
public class InquiryService : IInquiryService
{
    private readonly ITaxApiClient _taxApiClient;

    public InquiryService(ITaxApiClient taxApiClient)
    {
        _taxApiClient = taxApiClient ?? throw new ArgumentNullException(nameof(taxApiClient));
    }

    public async Task<List<InquiryResultDto>> InquiryByTimeAsync(InquiryByTimeRangeDto dto, CancellationToken cancellationToken = default)
    {
        if (dto == null)
        {
            throw new ArgumentNullException(nameof(dto));
        }

        return await _taxApiClient.InquiryByTimeAsync(dto, cancellationToken).ConfigureAwait(false);
    }

    public async Task<List<InquiryResultDto>> InquiryByUidAsync(InquiryByUidDto dto, CancellationToken cancellationToken = default)
    {
        if (dto == null)
        {
            throw new ArgumentNullException(nameof(dto));
        }

        return await _taxApiClient.InquiryByUidAsync(dto, cancellationToken).ConfigureAwait(false);
    }

    public async Task<List<InquiryResultDto>> InquiryByReferenceIdAsync(InquiryByReferenceNumberDto dto, CancellationToken cancellationToken = default)
    {
        if (dto == null)
        {
            throw new ArgumentNullException(nameof(dto));
        }

        return await _taxApiClient.InquiryByReferenceIdAsync(dto, cancellationToken).ConfigureAwait(false);
    }
}

