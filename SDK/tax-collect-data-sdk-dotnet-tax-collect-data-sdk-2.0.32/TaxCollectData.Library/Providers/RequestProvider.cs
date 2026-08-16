using System.Text;
using System.Web;
using TaxCollectData.Library.Abstraction.Providers;
using TaxCollectData.Library.Abstraction.Properties;
using TaxCollectData.Library.Dto;
using TaxCollectData.Library.Constants;

namespace TaxCollectData.Library.Providers;

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
    private readonly IUrlProperties _urlProperties;
    private readonly ISerializer _serializer;

    public RequestProvider(IUrlProperties urlProperties, ISerializer serializer)
    {
        _urlProperties = urlProperties;
        _serializer = serializer;
    }

    public HttpRequestMessage GetNonceRequest()
    {
        return new HttpRequestMessage(HttpMethod.Get, _urlProperties.GetUrl(PacketTypeConstants.NONCE));
    }

    public HttpRequestMessage GetServerInformation()
    {
        return new HttpRequestMessage(HttpMethod.Get,
            _urlProperties.GetUrl(PacketTypeConstants.GET_SERVER_INFORMATION));
    }

    public HttpRequestMessage GetInquiryByTimeRequest(InquiryByTimeRangeDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[Start] = dto.Start.ToString(DateTimeFormat);
        if (dto.End != null)
        {
            query[End] = dto.End?.ToString(DateTimeFormat);
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

        return GetRequestFromQuery(PacketTypeConstants.INQUIRY_BY_TIME_RANGE, query.ToString());
    }


    public HttpRequestMessage GetInquiryByUidRequest(InquiryByUidDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[FiscalId] = dto.FiscalId;
        dto.UidList.ForEach(u => query.Add(UidList, u));
        if (dto.Start != null)
        {
            query[Start] = dto.Start?.ToString(DateTimeFormat);
        }
        if (dto.End != null)
        {
            query[End] = dto.End?.ToString(DateTimeFormat);
        }
        return GetRequestFromQuery(PacketTypeConstants.INQUIRY_BY_UID, query.ToString());
    }


    public HttpRequestMessage GetInquiryByReferenceIdRequest(InquiryByReferenceNumberDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        dto.ReferenceNumbers.ForEach(u => query.Add(ReferenceIds, u));
        if (dto.Start != null)
        {
            query[Start] = dto.Start?.ToString(DateTimeFormat);
        }
        if (dto.End != null)
        {
            query[End] = dto.End?.ToString(DateTimeFormat);
        }
        return GetRequestFromQuery(PacketTypeConstants.INQUIRY_BY_REFERENCE_ID, query.ToString());
    }

    public HttpRequestMessage GetInvoicesRequest(List<PacketDto> data)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, _urlProperties.GetUrl(PacketTypeConstants.INVOICE));
        request.Content = new StringContent(_serializer.Serialize(data), Encoding.UTF8, MediaType);
        return request;
    }


    public HttpRequestMessage GetTaxpayerRequest(string economicCode)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[EconomicCode] = economicCode;
        return GetRequestFromQuery(PacketTypeConstants.GET_TAXPAYER, query.ToString());
    }


    public HttpRequestMessage GetFiscalInformationRequest(string memoryId)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[MemoryId] = memoryId;
        return GetRequestFromQuery(PacketTypeConstants.GET_FISCAL_INFORMATION, query.ToString());
    }
    
    public HttpRequestMessage GetTaxpayerInfoRequest(string economicCode)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[EconomicCode] = economicCode;
        return GetRequestFromQuery(PacketTypeConstants.GET_TAXPAYER_INFO, query.ToString());
    }
    
    public HttpRequestMessage GetTaxpayerArticle6Status(Article6StatusDto dto)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        query[EconomicCode] = dto.EconomicCode;
        query[VatValue] = dto.VatValue.ToString();
        query[Period] = dto.Period.ToString();
        return GetRequestFromQuery(PacketTypeConstants.GET_ARTICLE_6_STATUS, query.ToString());
    }

    public HttpRequestMessage GetInquiryInvoiceStatusRequest(List<string> taxIds)
    {
        var query = HttpUtility.ParseQueryString(string.Empty);
        taxIds.ForEach(u => query.Add(TaxIds, u));
        return GetRequestFromQuery(PacketTypeConstants.INQUIRY_INVOICE_STATUS, query.ToString());
    }

    public HttpRequestMessage GetRegisterPaymentRequest(RegisterPaymentRequestDto paymentRequestDto)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, _urlProperties.GetUrl(PacketTypeConstants.INVOICE_PAYMENT));
        request.Content = new StringContent(_serializer.Serialize(paymentRequestDto), Encoding.UTF8, MediaType);
        return request;
    }

    private HttpRequestMessage GetRequestFromQuery(string requestUrl, string query)
    {
        var uriBuilder = new UriBuilder(_urlProperties.GetUrl(requestUrl))
        {
            Query = query
        };
        return new HttpRequestMessage(HttpMethod.Get, uriBuilder.ToString());
    }
}