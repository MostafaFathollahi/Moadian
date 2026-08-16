using TaxCollectData.Library.Enums;

namespace TaxCollectData.Library.Models;

public class RegisterPaymentResultModel
{
    public RequestStatus RequestStatus { get; set; }
    public List<ErrorModel> Error { get; set; }
    public long createDate { get; set; }
}
