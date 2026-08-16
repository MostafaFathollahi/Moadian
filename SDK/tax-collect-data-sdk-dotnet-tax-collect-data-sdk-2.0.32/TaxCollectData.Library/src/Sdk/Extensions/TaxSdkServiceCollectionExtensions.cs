using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Http;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Application.Services;
using TaxCollectData.Library.Domain.Interfaces;
using TaxCollectData.Library.Domain.ValueObjects;
using TaxCollectData.Library.Infrastructure.Algorithms;
using TaxCollectData.Library.Infrastructure.Certificate;
using TaxCollectData.Library.Infrastructure.Crypto;
using TaxCollectData.Library.Infrastructure.ExternalApi;
using TaxCollectData.Library.Infrastructure.Http;
using TaxCollectData.Library.Infrastructure.Providers;
using TaxCollectData.Library.Infrastructure.Repository;
using TaxCollectData.Library.Infrastructure.Serialization;
using TaxCollectData.Library.Sdk.Configuration;
using TaxCollectData.Library.Sdk.Public;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace TaxCollectData.Library.Sdk.Extensions;

/// <summary>
/// Extension methods for registering Tax SDK services
/// </summary>
public static class TaxSdkServiceCollectionExtensions
{
    /// <summary>
    /// Adds Tax SDK services to the service collection
    /// </summary>
    public static IServiceCollection AddTaxSdk(this IServiceCollection services, TaxSdkOptions options)
    {
        if (services == null)
        {
            throw new ArgumentNullException(nameof(services));
        }

        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        options.Validate();

        // Register options
        services.AddSingleton(options);

        // Register HTTP client
        services.AddHttpClient("TaxSdk", client =>
        {
            client.Timeout = options.RequestTimeout;
        });

        // Register infrastructure services
        services.AddSingleton<IJsonSerializer, JsonSerializer>();
        services.AddSingleton<IErrorDetectionAlgorithm, VerhoeffAlgorithm>();
        services.AddSingleton<ICurrentDateProvider, CurrentDateProvider>();
        services.AddSingleton<ITaxIdProvider>(sp => new TaxIdProvider(sp.GetRequiredService<IErrorDetectionAlgorithm>()));

        // Register URL provider
        services.AddSingleton<IUrlProvider>(sp => new UrlProvider(options.BaseUrl, options.ApiVersion));

        // Register certificate loader and cryptography
        if (!string.IsNullOrWhiteSpace(options.PrivateKeyPath) && !string.IsNullOrWhiteSpace(options.CertificatePath))
        {
            // PKCS#8 configuration
            services.AddSingleton<ICertificateLoader, Pkcs8CertificateLoader>();
            services.AddSingleton<ISignatory>(sp =>
            {
                var loader = sp.GetRequiredService<ICertificateLoader>();
                var certificate = loader.LoadCertificate(options.CertificatePath);
                var privateKey = loader.LoadPrivateKey(options.PrivateKeyPath);
                var dateProvider = sp.GetRequiredService<ICurrentDateProvider>();
                var serializer = sp.GetRequiredService<IJsonSerializer>();
                return new JwsSignatory(certificate, privateKey, dateProvider, serializer);
            });
        }
        else if (!string.IsNullOrWhiteSpace(options.Pkcs11LibraryPath))
        {
            // TODO: Implement PKCS#11 support
            throw new NotImplementedException("PKCS#11 support is not yet implemented");
        }

        // Register encryption key repository (will be initialized after getting server info)
        services.AddSingleton<IEncryptionKeyRepository>(sp =>
        {
            // Lazy initialization - keys will be fetched when needed
            return new EncryptionKeyRepository(() =>
            {
                var taxApiClient = sp.GetRequiredService<ITaxApiClient>();
                var serverInfo = taxApiClient.GetServerInformationAsync().GetAwaiter().GetResult();
                return serverInfo.PublicKeys.Select(k => new TaxCollectData.Library.Application.DTOs.PublicKeyDto { Id = k.Id, Key = k.Key }).ToList();
            });
        });

        // Register encryptor
        services.AddSingleton<IEncryptor>(sp =>
        {
            var repository = sp.GetRequiredService<IEncryptionKeyRepository>();
            return new JweEncryptor(repository);
        });

        // Register ClientId value object
        services.AddSingleton<ClientId>(sp => new ClientId(options.ClientId));

        // Register request provider
        services.AddSingleton<IRequestProvider>(sp =>
        {
            var urlProvider = sp.GetRequiredService<IUrlProvider>();
            var serializer = sp.GetRequiredService<IJsonSerializer>();
            return new RequestProvider(urlProvider, serializer);
        });

        // Register HTTP client wrapper
        services.AddSingleton<IHttpClient>(sp =>
        {
            var httpClientFactory = sp.GetRequiredService<IHttpClientFactory>();
            var signatory = sp.GetRequiredService<ISignatory>();
            var clientId = sp.GetRequiredService<ClientId>();
            var serializer = sp.GetRequiredService<IJsonSerializer>();
            return new TaxHttpClient(httpClientFactory, signatory, clientId, serializer, options.CustomHeaders);
        });

        // Register Tax API client
        services.AddSingleton<ITaxApiClient>(sp =>
        {
            var httpClient = sp.GetRequiredService<IHttpClient>();
            var requestProvider = sp.GetRequiredService<IRequestProvider>();
            var serializer = sp.GetRequiredService<IJsonSerializer>();
            return new TaxApiClient(httpClient, requestProvider, serializer);
        });

        // Register application services
        services.AddScoped<IPacketService>(sp =>
        {
            var clientId = sp.GetRequiredService<ClientId>();
            var signatory = sp.GetRequiredService<ISignatory>();
            var encryptor = sp.GetRequiredService<IEncryptor>();
            var serializer = sp.GetRequiredService<IJsonSerializer>();
            return new PacketService(clientId, signatory, encryptor, serializer);
        });

        services.AddScoped<IInvoiceService, InvoiceService>();
        services.AddScoped<IInquiryService, InquiryService>();
        services.AddScoped<ITaxpayerService, TaxpayerService>();
        services.AddScoped<IPaymentService, PaymentService>();
        services.AddScoped<IAuthenticationService, AuthenticationService>();

        // Register main SDK
        services.AddScoped<TaxSdk>(sp =>
        {
            var invoiceService = sp.GetRequiredService<IInvoiceService>();
            var inquiryService = sp.GetRequiredService<IInquiryService>();
            var taxpayerService = sp.GetRequiredService<ITaxpayerService>();
            var paymentService = sp.GetRequiredService<IPaymentService>();
            return new TaxSdk(invoiceService, inquiryService, taxpayerService, paymentService);
        });

        return services;
    }
}

