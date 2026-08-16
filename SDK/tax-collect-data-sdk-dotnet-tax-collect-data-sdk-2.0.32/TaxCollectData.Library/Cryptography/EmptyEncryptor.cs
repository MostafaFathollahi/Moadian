using TaxCollectData.Library.Abstraction.Cryptography;

namespace TaxCollectData.Library.Cryptography;

public class EmptyEncryptor : IEncryptor
{
    public string Encrypt(string text)
    {
        return text;
    }
}