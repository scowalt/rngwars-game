namespace RNGWars

open Microsoft.AspNetCore.Builder
open Microsoft.AspNetCore.HttpOverrides

module ProxyHeadersConfig =

    let configure (options: ForwardedHeadersOptions) =
        options.ForwardedHeaders <- ForwardedHeaders.XForwardedFor ||| ForwardedHeaders.XForwardedProto
        options.ForwardedForHeaderName <- "CF-Connecting-IP"
        options.KnownIPNetworks.Clear()
        options.KnownProxies.Clear()
