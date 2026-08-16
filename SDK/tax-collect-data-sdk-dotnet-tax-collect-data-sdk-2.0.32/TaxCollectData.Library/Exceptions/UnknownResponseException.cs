using System.Net;

namespace TaxCollectData.Library.Exceptions;

public class UnknownResponseException : Exception
{
    public HttpStatusCode StatusCode { get; }
    public string Body { get; }

    public UnknownResponseException(HttpStatusCode statusCode, string body) : base($"HTTP_{statusCode}: {body}") {
        StatusCode = statusCode;
        Body = body;
    }

}