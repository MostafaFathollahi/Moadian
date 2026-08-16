using System.Text;
using System.Web;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.Serialization;

namespace TaxCollectData.Library.Infrastructure.ExternalApi;

/// <summary>
/// Low-level client for Tax API
/// </summary>
public class TaxApiClient : ITaxApiClient
{
    private const string MediaType = "application/json";
    private const string DateTimeFormat = "yyyy-MM-ddTHH:mm:ss.fffffff00K";
    
    private readonly IHttpClient _httpClient;
    private readonly IRequestProvider _requestProvider;
    private readonly IJsonSerializer _serializer;

    public TaxApiClient(IHttpClient httpClient, IRequestProvider requestProvider, IJsonSerializer serializer)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _requestProvider = requestProvider ?? throw new ArgumentNullException(nameof(requestProvider));
        _serializer = serializer ?? throw new ArgumentNullException(nameof(serializer));
    }

    public async Task<BatchResponseDto> SendInvoicesAsync(List<PacketDto> packets, CancellationToken cancellationToken = default)
    {
        if (packets == null || packets.Count == 0)
        {
            throw new ArgumentException("Packets list cannot be null or empty", nameof(packets));
        }

        var request = _requestProvider.GetInvoicesRequest(packets);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<BatchResponseDto>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<List<InquiryResultDto>> InquiryByTimeAsync(InquiryByTimeRangeDto dto, CancellationToken cancellationToken = default)
    {
        if (dto == null)
        {
            throw new ArgumentNullException(nameof(dto));
        }

        var request = _requestProvider.GetInquiryByTimeRequest(dto);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<List<InquiryResultDto>>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<List<InquiryResultDto>> InquiryByUidAsync(InquiryByUidDto dto, CancellationToken cancellationToken = default)
    {
        if (dto == null)
        {
            throw new ArgumentNullException(nameof(dto));
        }

        var request = _requestProvider.GetInquiryByUidRequest(dto);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<List<InquiryResultDto>>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<List<InquiryResultDto>> InquiryByReferenceIdAsync(InquiryByReferenceNumberDto dto, CancellationToken cancellationToken = default)
    {
        if (dto == null)
        {
            throw new ArgumentNullException(nameof(dto));
        }

        var request = _requestProvider.GetInquiryByReferenceIdRequest(dto);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<List<InquiryResultDto>>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<List<InvoiceStatusInquiryResponseDto>> InquiryInvoiceStatusAsync(List<string> taxIds, CancellationToken cancellationToken = default)
    {
        if (taxIds == null || taxIds.Count == 0)
        {
            throw new ArgumentException("TaxIds list cannot be null or empty", nameof(taxIds));
        }

        var request = _requestProvider.GetInquiryInvoiceStatusRequest(taxIds);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<List<InvoiceStatusInquiryResponseDto>>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<TaxpayerDto> GetTaxpayerAsync(string economicCode, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(economicCode))
        {
            throw new ArgumentException("Economic code cannot be null or empty", nameof(economicCode));
        }

        var request = _requestProvider.GetTaxpayerRequest(economicCode);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<TaxpayerDto>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ServerInformationDto> GetServerInformationAsync(CancellationToken cancellationToken = default)
    {
        var request = _requestProvider.GetServerInformation();
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<ServerInformationDto>(request, nonceRequest, cancellationToken).ConfigureAwait(false);
    }

    public async Task<RegisterPaymentResultDto> RegisterPaymentAsync(RegisterPaymentRequestDto request, CancellationToken cancellationToken = default)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        var httpRequest = _requestProvider.GetRegisterPaymentRequest(request);
        var nonceRequest = _requestProvider.GetNonceRequest();
        return await _httpClient.SendAsync<RegisterPaymentResultDto>(httpRequest, nonceRequest, cancellationToken).ConfigureAwait(false);
    }
}

