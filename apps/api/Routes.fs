namespace RNGWars

open Giraffe

module Routes =

    let webApp: HttpHandler =
        choose
            [ GET >=> route "/api/health" >=> ApiHandlers.healthCheck
              GET >=> route "/api/leaderboard" >=> ApiHandlers.getLeaderboard
              POST >=> route "/api/users/anonymous" >=> ApiHandlers.createAnonymousUser
              GET
              >=> route "/api/users/me"
              >=> Auth.requireAuth
              >=> ApiHandlers.getMe
              PUT
              >=> route "/api/users/me"
              >=> Auth.requireAuth
              >=> ApiHandlers.updateMe
              GET
              >=> route "/api/users/me/matches"
              >=> Auth.requireAuth
              >=> ApiHandlers.getMyMatches
              POST
              >=> route "/api/matches/practice"
              >=> Auth.requireAuth
              >=> ApiHandlers.startPractice
              GET
              >=> routef "/api/matches/%s" (fun matchId ->
                  Auth.requireAuth >=> ApiHandlers.getMatch matchId)
              GET
              >=> routef "/auth/%s/callback" (fun provider ->
                  OAuthHandlers.authCallback provider)
              GET
              >=> routef "/auth/%s" (fun provider ->
                  OAuthHandlers.startAuth provider) ]
