using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using JWT;
using JWT.Algorithms;
using JWT.Builder;
using Microsoft.Extensions.Logging;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Security;
using TaxCollectData.Library.Domain.Interfaces;
using TaxCollectData.Library.Infrastructure.Serialization;
using JwtIJsonSerializer = JWT.IJsonSerializer;
using SdkIJsonSerializer = TaxCollectData.Library.Infrastructure.Serialization.IJsonSerializer;

namespace TaxCollectData.Library.Infrastructure.Crypto;

/// <summary>
/// JWS (JSON Web Signature) signatory implementation
/// </summary>
public class JwsSignatory : ISignatory
{
    private const string Jose = "jose";
    private const string SigT = "sigT";
    private const string Typ = "typ";
    private const string Crit = "crit";
    private const string Cty = "cty";
    private const string ContentTypeHeaderValue = "text/plain";

    private readonly X509Certificate _certificate;
    private readonly RSA _privateKey;
    private readonly ICurrentDateProvider _currentDateProvider;
    private readonly SdkIJsonSerializer _jsonSerializer;
    private readonly ILogger<JwsSignatory>? _logger;

    public JwsSignatory(
        X509Certificate certificate,
        RSA privateKey,
        ICurrentDateProvider currentDateProvider,
        SdkIJsonSerializer jsonSerializer,
        ILogger<JwsSignatory>? logger = null)
    {
        _certificate = certificate ?? throw new ArgumentNullException(nameof(certificate));
        _privateKey = privateKey ?? throw new ArgumentNullException(nameof(privateKey));
        _currentDateProvider = currentDateProvider ?? throw new ArgumentNullException(nameof(currentDateProvider));
        _jsonSerializer = jsonSerializer ?? throw new ArgumentNullException(nameof(jsonSerializer));
        _logger = logger;
    }

    public string Sign(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new ArgumentException("Text cannot be null or empty", nameof(text));
        }

        var stopwatch = Stopwatch.StartNew();
        try
        {
            var publicKey = DotNetUtilities.ToRSA(
                (RsaKeyParameters)DotNetUtilities.FromX509Certificate(_certificate).GetPublicKey());
            
            var jsonNode = System.Text.Json.JsonSerializer.Deserialize<JsonNode>(text, _jsonSerializer.GetJsonSerializerOptions());
            
            return JwtBuilder.Create()
                .WithJsonSerializer(new CustomSerializer(_jsonSerializer))
                .WithAlgorithm(new RS256Algorithm(publicKey, _privateKey))
                .AddHeader(HeaderName.X5c, new[] { Convert.ToBase64String(_certificate.GetRawCertData()) })
                .AddHeader(SigT, _currentDateProvider.ToDateFormat())
                .AddHeader(Typ, Jose)
                .AddHeader(Crit, new[] { SigT })
                .AddHeader(Cty, ContentTypeHeaderValue)
                .Encode(jsonNode);
        }
        finally
        {
            stopwatch.Stop();
            _logger?.LogDebug("Signing completed in {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
        }
    }

    public string Sign(object data)
    {
        if (data == null)
        {
            throw new ArgumentNullException(nameof(data));
        }

        var stopwatch = Stopwatch.StartNew();
        try
        {
            var publicKey = DotNetUtilities.ToRSA(
                (RsaKeyParameters)DotNetUtilities.FromX509Certificate(_certificate).GetPublicKey());
            
            return JwtBuilder.Create()
                .WithJsonSerializer(new CustomSerializer(_jsonSerializer))
                .WithAlgorithm(new RS256Algorithm(publicKey, _privateKey))
                .AddHeader(HeaderName.X5c, new[] { Convert.ToBase64String(_certificate.GetRawCertData()) })
                .AddHeader(SigT, _currentDateProvider.ToDateFormat())
                .AddHeader(Typ, Jose)
                .AddHeader(Crit, new[] { SigT })
                .AddHeader(Cty, ContentTypeHeaderValue)
                .Encode(data);
        }
        finally
        {
            stopwatch.Stop();
            _logger?.LogDebug("Signing completed in {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
        }
    }

    private class CustomSerializer : JwtIJsonSerializer
    {
        private readonly SdkIJsonSerializer _jsonSerializer;

        public CustomSerializer(SdkIJsonSerializer jsonSerializer)
        {
            _jsonSerializer = jsonSerializer;
        }

        public string Serialize(object obj)
        {
            return _jsonSerializer.Serialize(obj);
        }

        public object? Deserialize(Type type, string json)
        {
            return _jsonSerializer.Deserialize<object>(json);
        }
    }
}

