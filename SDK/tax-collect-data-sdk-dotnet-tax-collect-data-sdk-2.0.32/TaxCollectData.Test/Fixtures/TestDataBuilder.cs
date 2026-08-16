using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Domain.Enums;

namespace TaxCollectData.Test.Fixtures;

/// <summary>
/// Builder for creating test data
/// </summary>
public static class TestDataBuilder
{
    public static InvoiceDto CreateValidInvoice(string taxId = "TAX001")
    {
        return new InvoiceDto
        {
            Header = new HeaderDto
            {
                taxid = taxId,
                indatim = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ins = 1,
                inty = 1,
                inp = 1,
                tins = "14003778990",
                tinb = "10100302746",
                tprdis = 20_000,
                tdis = 500,
                tadis = 19_500,
                tvam = 1_755,
                todam = 0,
                tbill = 21_255,
                setm = 2
            },
            Body = new List<BodyItemDto>
            {
                new()
                {
                    sstid = "2710000138624",
                    sstt = "Test Product",
                    mu = "164",
                    am = 2,
                    fee = 10_000,
                    prdis = 20_000,
                    dis = 500,
                    adis = 19_500,
                    vra = 9,
                    vam = 1_755,
                    tsstam = 21_255
                }
            },
            Payments = new List<PaymentItemDto>(),
            Extension = new List<ExtensionItemDto>()
        };
    }

    public static RegisterPaymentRequestDto CreatePaymentRequest(string taxId = "TAX001")
    {
        return new RegisterPaymentRequestDto
        {
            TaxId = taxId,
            PaidAmount = 100000,
            PaymentDate = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            PaymentMethod = PaymentMethod.Cash,
            TerminalNumber = "TERM001",
            ReferenceNumber = "REF001"
        };
    }

    public static InquiryByTimeRangeDto CreateInquiryByTimeRangeDto()
    {
        return new InquiryByTimeRangeDto(
            DateTime.Now.AddDays(-1),
            DateTime.Now,
            new Pageable(0, 10),
            RequestStatus.SUCCESS);
    }
}

