using TaxCollectData.Library.Dto;

namespace TaxCollectData.Library.Exceptions
{
    internal class TaxCollectionApiException : Exception
    {
        public ErrorResponseDto? ErrorResponse { get; }

        public TaxCollectionApiException(ErrorResponseDto? errorResponse) : base(errorResponse?.ToString())
        {
            ErrorResponse = errorResponse;
        }
    }
}