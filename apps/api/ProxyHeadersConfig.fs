namespace RNGWars

open Microsoft.AspNetCore.Builder
open Microsoft.AspNetCore.HttpOverrides

module ProxyHeadersConfig =

    let configure (options: ForwardedHeadersOptions) =
        options.ForwardedHeaders <- ForwardedHeaders.XForwardedProto
        options.KnownIPNetworks.Clear()
        options.KnownProxies.Clear()
