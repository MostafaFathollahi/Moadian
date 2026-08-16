using System.Text;
using System.Web;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.Serialization;

namespace TaxCollectData.Library.Infrastructure.Http;

/// <summary>
/// Provider for creating HTTP requests to Tax API
/// </summary>
public class RequestProvider : IRequestProvider
{
    private const string MemoryId = "memoryId";
    private const string EconomicCode = "economicCode";
    private const string VatValue = "vatValue";
    private const string Period = "period";
    private const string ReferenceIds = "referenceIds";
    private const string UidList = "uidList";
    private const string FiscalId = "fiscalId";
    private const string PageSize = "pageSize";
    private const string PageNumber = "pageNumber";
    private const string End = "end";
    private const string Start = "start";
    private const string Status = "status";
    private const string MediaType = "application/json";
    private const string DateTimeFormat = "yyyy-MM-ddTHH:mm:ss.fffffff00K";
    private const string TaxIds = "taxIds";

    private readonly IUrlProvider _urlProvider;
    private readonly IJsonSerializer _serializer;

    public RequestProvider(IUrlProvider urlProvider, IJsonSerializer serializer)
    {
        _urlProvider = urlProvider ?? throw new ArgumentNullException(nameof(urlProvider));
        _serializer = serializer ?? throw new ArgumentNullException(nameof(serializer));
    }

    public HttpRequestMessage GetNonceRequest()
    {
        return new HttpRequestMessage(HttpMethod.Get, _urlProvider.GetUrl("nonce"));
    }

    public HttpRequestMessage GetServerInformation()
    {
        return new HttpRequestMessage(HttpMethod.Get, _urlProvider.GetUrl("server-information"));
    }

    public HttpRequestMessage GetInquiryByTimeRequest(InquiryByTimeRangeDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[Start] = dto.Start.ToString(DateTimeFormat);
        
        if (dto.End != null)
        {
            query[End] = dto.End.Value.ToString(DateTimeFormat);
        }

        if (dto.Status != null)
        {
            query[Status] = dto.Status.ToString();
        }

        if (dto.Pageable != null)
        {
            query[PageNumber] = dto.Pageable.PageNumber.ToString();
            query[PageSize] = dto.Pageable.PageSize.ToString();
        }

        return GetRequestFromQuery("inquiry", query.ToString());
    }

    public HttpRequestMessage GetInquiryByUidRequest(InquiryByUidDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[FiscalId] = dto.FiscalId;
        
        foreach (var uid in dto.UidList)
        {
            query.Add(UidList, uid);
        }
        
        if (dto.Start != null)
        {
            query[Start] = dto.Start.Value.ToString(DateTimeFormat);
        }
        
        if (dto.End != null)
        {
            query[End] = dto.End.Value.ToString(DateTimeFormat);
        }
        
        return GetRequestFromQuery("inquiry-by-uid", query.ToString());
    }

    public HttpRequestMessage GetInquiryByReferenceIdRequest(InquiryByReferenceNumberDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        
        foreach (var referenceId in dto.ReferenceNumbers)
        {
            query.Add(ReferenceIds, referenceId);
        }
        
        if (dto.Start != null)
        {
            query[Start] = dto.Start.Value.ToString(DateTimeFormat);
        }
        
        if (dto.End != null)
        {
            query[End] = dto.End.Value.ToString(DateTimeFormat);
        }
        
        return GetRequestFromQuery("inquiry-by-reference-id", query.ToString());
    }

    public HttpRequestMessage GetInvoicesRequest(List<PacketDto> packets)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, _urlProvider.GetUrl("invoice"));
        var json = _serializer.Serialize(packets);
        request.Content = new StringContent(json, Encoding.UTF8, MediaType);
        return request;
    }

    public HttpRequestMessage GetTaxpayerRequest(string economicCode)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[EconomicCode] = economicCode;
        return GetRequestFromQuery("taxpayer", query.ToString());
    }

    public HttpRequestMessage GetRegisterPaymentRequest(RegisterPaymentRequestDto request)
    {
        var httpRequest = new HttpRequestMessage(HttpMethod.Post, _urlProvider.GetUrl("invoice-payment"));
        var json = _serializer.Serialize(request);
        httpRequest.Content = new StringContent(json, Encoding.UTF8, MediaType);
        return httpRequest;
    }

    public HttpRequestMessage GetInquiryInvoiceStatusRequest(List<string> taxIds)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        
        foreach (var taxId in taxIds)
        {
            query.Add(TaxIds, taxId);
        }
        
        return GetRequestFromQuery("inquiry-invoice-status", query.ToString());
    }

    private HttpRequestMessage GetRequestFromQuery(string requestUrl, string query)
    {
        var uriBuilder = new UriBuilder(_urlProvider.GetUrl(requestUrl))
        {
            Query = query
        };
        return new HttpRequestMessage(HttpMethod.Get, uriBuilder.ToString());
    }
}

