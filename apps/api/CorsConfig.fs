namespace RNGWars

open Microsoft.AspNetCore.Cors.Infrastructure

module CorsConfig =

    let productionOrigins = [| "https://play.rngwars.com" |]

    let developmentOrigins = [| "http://localhost:5173"; "http://localhost:3000" |]

    let allowedOrigins (isDevelopment: bool) =
        if isDevelopment then
            Array.append productionOrigins developmentOrigins
        else
            productionOrigins

    let configure (isDevelopment: bool) (options: CorsOptions) =
        options.AddDefaultPolicy(fun policy ->
            policy
                .WithOrigins(allowedOrigins isDevelopment)
                .AllowAnyHeader()
                .AllowAnyMethod()
                .AllowCredentials()
            |> ignore)
