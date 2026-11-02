namespace RNGWars

open System
open Microsoft.AspNetCore.Http
open Sentry
open Sentry.Protocol
open Giraffe

module Auth =

    [<Literal>]
    let UserContextKey = "CurrentUser"

    let extractToken (ctx: HttpContext) : string option =
        let authHeader = ctx.Request.Headers.Authorization.ToString()

        if authHeader.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase) then
            let token = authHeader.Substring(7).Trim()
            match Guid.TryParse(token) with
            | true, _ -> Some token
            | false, _ -> None
        else
            None

    let requireAuth: HttpHandler =
        fun next ctx ->
            task {
                match extractToken ctx with
                | None ->
                    ctx.SetStatusCode 401

                    return!
                        json
                            { Error =
                                { Code = "UNAUTHORIZED"
                                  Message = "Missing or invalid authorization token" } }
                            earlyReturn
                            ctx
                | Some token ->
                    match Database.getUserByToken token with
                    | None ->
                        ctx.SetStatusCode 401

                        return!
                            json
                                { Error =
                                    { Code = "UNAUTHORIZED"
                                      Message = "Invalid token" } }
                                earlyReturn
                                ctx
                    | Some user ->
                        ctx.Items[UserContextKey] <- box user
                        Database.updateLastSeen user.Id
                        SentrySdk.ConfigureScope(fun scope ->
                            scope.User <- SentryUser(Id = user.Id, Username = user.Username))
                        return! next ctx
            }

    let getCurrentUser (ctx: HttpContext) : User =
        ctx.Items[UserContextKey] :?> User
