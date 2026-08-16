namespace TaxCollectData.Library.Models;

public class ErrorModel
{
    public ErrorModel(string code, string message)
    {
        Code = code;
        Message = message;
    }

    public string Code { get; }
    public string Message { get; }
}