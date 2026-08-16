using TaxCollectData.Library.Dto;

namespace TaxCollectData.Library.Abstraction.Providers;

public interface IRequestProvider
{
    HttpRequestMessage GetNonceRequest();

    HttpRequestMessage GetServerInformation();

    HttpRequestMessage GetInquiryByTimeRequest(InquiryByTimeRangeDto dto);

    HttpRequestMessage GetInquiryByUidRequest(InquiryByUidDto dto);

    HttpRequestMessage GetInquiryByReferenceIdRequest(InquiryByReferenceNumberDto dto);

    HttpRequestMessage GetInvoicesRequest(List<PacketDto> data);

    HttpRequestMessage GetTaxpayerRequest(string economicCode);

    HttpRequestMessage GetFiscalInformationRequest(string memoryId);

    HttpRequestMessage GetTaxpayerInfoRequest(string economicCode);

    HttpRequestMessage GetTaxpayerArticle6Status(Article6StatusDto dto);
    
    HttpRequestMessage GetInquiryInvoiceStatusRequest(List<string> taxIds);
    
    HttpRequestMessage GetRegisterPaymentRequest(RegisterPaymentRequestDto paymentRequestDto);
}