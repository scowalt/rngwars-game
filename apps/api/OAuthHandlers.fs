namespace RNGWars

open System
open System.Collections.Generic
open System.Net.Http
open System.Text.Json
open Microsoft.AspNetCore.Http
open Sentry
open Giraffe

module OAuthHandlers =

    type OAuthConfig =
        { ClientId: string
          ClientSecret: string
          AuthorizeUrl: string
          TokenUrl: string
          UserInfoUrl: string
          Scopes: string }

    let private configs =
        dict [
            "github", fun () ->
                { ClientId = Environment.GetEnvironmentVariable("GITHUB_CLIENT_ID") |> Option.ofObj |> Option.defaultValue ""
                  ClientSecret = Environment.GetEnvironmentVariable("GITHUB_CLIENT_SECRET") |> Option.ofObj |> Option.defaultValue ""
                  AuthorizeUrl = "https://github.com/login/oauth/authorize"
                  TokenUrl = "https://github.com/login/oauth/access_token"
                  UserInfoUrl = "https://api.github.com/user"
                  Scopes = "read:user user:email" }
            "google", fun () ->
                { ClientId = Environment.GetEnvironmentVariable("GOOGLE_CLIENT_ID") |> Option.ofObj |> Option.defaultValue ""
                  ClientSecret = Environment.GetEnvironmentVariable("GOOGLE_CLIENT_SECRET") |> Option.ofObj |> Option.defaultValue ""
                  AuthorizeUrl = "https://accounts.google.com/o/oauth2/v2/auth"
                  TokenUrl = "https://oauth2.googleapis.com/token"
                  UserInfoUrl = "https://www.googleapis.com/oauth2/v2/userinfo"
                  Scopes = "openid email profile" }
            "discord", fun () ->
                { ClientId = Environment.GetEnvironmentVariable("DISCORD_CLIENT_ID") |> Option.ofObj |> Option.defaultValue ""
                  ClientSecret = Environment.GetEnvironmentVariable("DISCORD_CLIENT_SECRET") |> Option.ofObj |> Option.defaultValue ""
                  AuthorizeUrl = "https://discord.com/api/oauth2/authorize"
                  TokenUrl = "https://discord.com/api/oauth2/token"
                  UserInfoUrl = "https://discord.com/api/users/@me"
                  Scopes = "identify email" }
        ]

    let private getCallbackUrl (ctx: HttpContext) (provider: string) =
        let scheme = if ctx.Request.IsHttps then "https" else "http"
        let host = ctx.Request.Host.ToString()
        sprintf "%s://%s/auth/%s/callback" scheme host provider

    type private OAuthUserInfo =
        { AuthId: string
          Email: string option
          DisplayName: string option
          AvatarUrl: string option }

    let private exchangeCodeForToken (httpClient: HttpClient) (config: OAuthConfig) (code: string) (redirectUri: string) =
        task {
            let content =
                new FormUrlEncodedContent(
                    [ KeyValuePair("client_id", config.ClientId)
                      KeyValuePair("client_secret", config.ClientSecret)
                      KeyValuePair("code", code)
                      KeyValuePair("redirect_uri", redirectUri)
                      KeyValuePair("grant_type", "authorization_code") ])

            use request = new HttpRequestMessage(HttpMethod.Post, config.TokenUrl)
            request.Content <- content
            request.Headers.Accept.Add(System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("application/json"))

            let! response = httpClient.SendAsync(request)
            let! body = response.Content.ReadAsStringAsync()
            let doc = JsonDocument.Parse(body)
            return doc.RootElement.GetProperty("access_token").GetString()
        }

    let private fetchUserInfo (httpClient: HttpClient) (provider: string) (config: OAuthConfig) (accessToken: string) =
        task {
            use request = new HttpRequestMessage(HttpMethod.Get, config.UserInfoUrl)
            request.Headers.Authorization <- System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", accessToken)
            request.Headers.Add("User-Agent", "RNGWars")

            let! response = httpClient.SendAsync(request)
            let! body = response.Content.ReadAsStringAsync()
            let doc = JsonDocument.Parse(body)
            let root = doc.RootElement

            let tryGet (name: string) =
                match root.TryGetProperty(name) with
                | true, prop when prop.ValueKind <> JsonValueKind.Null -> Some (prop.GetString())
                | _ -> None

            match provider with
            | "github" ->
                return
                    { AuthId = root.GetProperty("id").GetInt64().ToString()
                      Email = tryGet "email"
                      DisplayName = tryGet "name" |> Option.orElse (tryGet "login")
                      AvatarUrl = tryGet "avatar_url" }
            | "google" ->
                return
                    { AuthId = root.GetProperty("id").GetString()
                      Email = tryGet "email"
                      DisplayName = tryGet "name"
                      AvatarUrl = tryGet "picture" }
            | "discord" ->
                let discordId = root.GetProperty("id").GetString()
                let avatar = tryGet "avatar"
                let avatarUrl =
                    avatar |> Option.map (fun a -> sprintf "https://cdn.discordapp.com/avatars/%s/%s.png" discordId a)
                return
                    { AuthId = discordId
                      Email = tryGet "email"
                      DisplayName = tryGet "global_name" |> Option.orElse (tryGet "username")
                      AvatarUrl = avatarUrl }
            | _ -> return failwith "Unknown provider"
        }

    let private linkOrCreateUser (provider: string) (info: OAuthUserInfo) (anonymousToken: string option) =
        match Database.getUserByAuthId provider info.AuthId with
        | Some existingUser ->
            match anonymousToken with
            | Some token ->
                match Database.getUserByToken token with
                | Some anonUser when anonUser.IsAnonymous && anonUser.Id <> existingUser.Id ->
                    Database.mergeAnonymousIntoExisting anonUser.Id existingUser.Id
                    |> Option.defaultValue existingUser
                | _ -> existingUser
            | None -> existingUser

        | None ->
            match anonymousToken with
            | Some token ->
                match Database.getUserByToken token with
                | Some anonUser when anonUser.IsAnonymous ->
                    Database.linkAnonymousToAuth anonUser.Id provider info.AuthId info.Email info.DisplayName info.AvatarUrl
                    |> Option.defaultValue anonUser
                | _ ->
                    let user = Database.createAnonymousUser ()
                    Database.linkAnonymousToAuth user.Id provider info.AuthId info.Email info.DisplayName info.AvatarUrl
                    |> Option.defaultValue user
            | None ->
                let user = Database.createAnonymousUser ()
                Database.linkAnonymousToAuth user.Id provider info.AuthId info.Email info.DisplayName info.AvatarUrl
                |> Option.defaultValue user

    let startAuth (provider: string) : HttpHandler =
        fun next ctx ->
            task {
                match configs.TryGetValue(provider) with
                | false, _ ->
                    ctx.SetStatusCode 404
                    return! json { Error = { Code = "UNKNOWN_PROVIDER"; Message = sprintf "Unknown provider: %s" provider } } next ctx
                | true, getConfig ->
                    let config = getConfig ()
                    if String.IsNullOrEmpty(config.ClientId) then
                        ctx.SetStatusCode 503
                        return! json { Error = { Code = "NOT_CONFIGURED"; Message = sprintf "%s OAuth is not configured" provider } } next ctx
                    else
                        let redirectUri = getCallbackUrl ctx provider
                        let state =
                            ctx.Request.Query["token"].ToString()
                            |> fun t -> if String.IsNullOrEmpty(t) then Guid.NewGuid().ToString() else t

                        let url =
                            sprintf "%s?client_id=%s&redirect_uri=%s&scope=%s&state=%s&response_type=code"
                                config.AuthorizeUrl
                                (Uri.EscapeDataString config.ClientId)
                                (Uri.EscapeDataString redirectUri)
                                (Uri.EscapeDataString config.Scopes)
                                (Uri.EscapeDataString state)

                        ctx.Response.Redirect(url)
                        return! next ctx
            }

    let authCallback (provider: string) : HttpHandler =
        fun next ctx ->
            task {
                match configs.TryGetValue(provider) with
                | false, _ ->
                    ctx.SetStatusCode 404
                    return! json { Error = { Code = "UNKNOWN_PROVIDER"; Message = sprintf "Unknown provider: %s" provider } } next ctx
                | true, getConfig ->
                    let config = getConfig ()
                    let code = ctx.Request.Query["code"].ToString()
                    let state = ctx.Request.Query["state"].ToString()

                    if String.IsNullOrEmpty(code) then
                        ctx.SetStatusCode 400
                        return! json { Error = { Code = "MISSING_CODE"; Message = "OAuth code not provided" } } next ctx
                    else
                        let! linked =
                            task {
                                try
                                    let redirectUri = getCallbackUrl ctx provider
                                    let httpClient = ctx.GetService<IHttpClientFactory>().CreateClient()
                                    let! accessToken = exchangeCodeForToken httpClient config code redirectUri
                                    let! userInfo = fetchUserInfo httpClient provider config accessToken

                                    let anonymousToken =
                                        match Guid.TryParse(state) with
                                        | true, _ -> Some state
                                        | _ -> None

                                    return Ok(linkOrCreateUser provider userInfo anonymousToken)
                                with ex ->
                                    SentrySdk.CaptureException(ex) |> ignore
                                    return Error()
                            }

                        match linked with
                        | Ok user ->
                            ctx.Response.Redirect(sprintf "/auth/success?token=%s" (Uri.EscapeDataString user.AnonymousId))
                        | Error() -> ctx.Response.Redirect("/?auth_error=OAUTH_ERROR")

                        return! next ctx
            }
