using System.Security.Cryptography;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Security;
using Org.BouncyCastle.Utilities.Encoders;
using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Infrastructure.Repository;

/// <summary>
/// Repository for managing encryption keys with caching
/// </summary>
public class EncryptionKeyRepository : IEncryptionKeyRepository
{
    private readonly Random _random = new();
    private readonly Func<List<PublicKeyDto>> _keyProvider;
    private RSA? _key;
    private string? _keyId;
    private DateTime _expiredTime;
    private readonly object _lockObject = new();

    public EncryptionKeyRepository(Func<List<PublicKeyDto>> keyProvider)
    {
        _keyProvider = keyProvider ?? throw new ArgumentNullException(nameof(keyProvider));
    }

    public RSA GetKey()
    {
        if (NeedRefresh())
        {
            Refresh();
        }

        return _key!;
    }

    public string GetKeyId()
    {
        if (NeedRefresh())
        {
            Refresh();
        }

        return _keyId!;
    }

    private void Refresh()
    {
        lock (_lockObject)
        {
            if (!NeedRefresh())
            {
                return;
            }

            var keyModels = _keyProvider.Invoke();
            if (keyModels == null || keyModels.Count == 0)
            {
                throw new InvalidOperationException("No encryption keys available");
            }

            var keyModel = keyModels[_random.Next(keyModels.Count)];
            _key = GetPublicKeyFromBase64(keyModel.Key);
            _keyId = keyModel.Id;
            _expiredTime = DateTime.Now.AddHours(1).ToLocalTime();
        }
    }

    private bool NeedRefresh()
    {
        return _key == null || _keyId == null || DateTime.Now.ToLocalTime() > _expiredTime;
    }

    private static RSA GetPublicKeyFromBase64(string key)
    {
        var decoded = Base64.Decode(key);
        var asymmetricKeyParameter = PublicKeyFactory.CreateKey(decoded);
        var rsaParams = DotNetUtilities.ToRSAParameters((RsaKeyParameters)asymmetricKeyParameter);
        var rsa = RSA.Create();
        rsa.ImportParameters(rsaParams);
        return rsa;
    }
}

