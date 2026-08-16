using System.Diagnostics;
using Microsoft.Extensions.Logging;
using Jose;
using TaxCollectData.Library.Infrastructure.Repository;

namespace TaxCollectData.Library.Infrastructure.Crypto;

/// <summary>
/// JWE (JSON Web Encryption) encryptor implementation
/// </summary>
public class JweEncryptor : IEncryptor
{
    private readonly IEncryptionKeyRepository _repository;
    private readonly ILogger<JweEncryptor>? _logger;

    public JweEncryptor(IEncryptionKeyRepository repository, ILogger<JweEncryptor>? logger = null)
    {
        _repository = repository ?? throw new ArgumentNullException(nameof(repository));
        _logger = logger;
    }

    public string Encrypt(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new ArgumentException("Text cannot be null or empty", nameof(text));
        }

        var stopwatch = Stopwatch.StartNew();
        try
        {
            var header = new Dictionary<string, object>
            {
                { "kid", _repository.GetKeyId() }
            };
            
            var recipient = new JweRecipient(JweAlgorithm.RSA_OAEP_256, _repository.GetKey(), header);
            return JWE.Encrypt(text, new[] { recipient }, JweEncryption.A256GCM, mode: SerializationMode.Compact);
        }
        finally
        {
            stopwatch.Stop();
            _logger?.LogDebug("Encryption completed in {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
        }
    }
}

