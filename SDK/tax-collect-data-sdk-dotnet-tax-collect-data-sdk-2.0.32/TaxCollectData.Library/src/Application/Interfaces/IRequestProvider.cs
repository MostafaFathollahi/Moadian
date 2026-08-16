using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Provider for creating HTTP requests
/// </summary>
public interface IRequestProvider
{
    HttpRequestMessage GetNonceRequest();
    HttpRequestMessage GetServerInformation();
    HttpRequestMessage GetInquiryByTimeRequest(InquiryByTimeRangeDto dto);
    HttpRequestMessage GetInquiryByUidRequest(InquiryByUidDto dto);
    HttpRequestMessage GetInquiryByReferenceIdRequest(InquiryByReferenceNumberDto dto);
    HttpRequestMessage GetInvoicesRequest(List<PacketDto> packets);
    HttpRequestMessage GetTaxpayerRequest(string economicCode);
    HttpRequestMessage GetRegisterPaymentRequest(RegisterPaymentRequestDto request);
    HttpRequestMessage GetInquiryInvoiceStatusRequest(List<string> taxIds);
}

