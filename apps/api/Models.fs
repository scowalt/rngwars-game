namespace RNGWars

open System

[<AutoOpen>]
module Models =

    type User =
        { Id: string
          Username: string
          AnonymousId: string
          AuthProvider: string option
          AuthId: string option
          Email: string option
          DisplayName: string option
          AvatarUrl: string option
          IsAnonymous: bool
          LinkedAt: string option
          RngScore: int
          TotalWins: int
          TotalLosses: int
          TotalMatches: int
          CreatedAt: string
          LastSeenAt: string }

    type Match =
        { Id: string
          Player1Id: string
          Player2Id: string option
          WinnerId: string option
          Status: string
          IsPractice: bool
          AiName: string option
          Player1Roll: float option
          Player2Roll: float option
          Player1EloBefore: int option
          Player2EloBefore: int option
          Player1EloAfter: int option
          Player2EloAfter: int option
          StartedAt: string option
          CompletedAt: string option
          CreatedAt: string }


    type UserResponse =
        { Id: string
          Username: string
          AvatarUrl: string option
          IsAnonymous: bool
          RngScore: int
          TotalWins: int
          TotalLosses: int
          TotalMatches: int }

    type CreateAnonymousResponse =
        { Token: string
          User: UserResponse }

    type UpdateUsernameRequest =
        { Username: string }

    type MatchResponse =
        { Id: string
          OpponentName: string
          OpponentElo: int option
          PlayerRoll: float option
          OpponentRoll: float option
          PlayerEloBefore: int option
          PlayerEloAfter: int option
          Won: bool option
          IsPractice: bool
          Status: string
          CompletedAt: string option }

    type MatchListResponse =
        { Matches: MatchResponse list
          HasMore: bool }

    type PracticeStartResponse =
        { MatchId: string
          OpponentName: string }

    type LeaderboardEntry =
        { Rank: int
          UserId: string
          Username: string
          RngScore: int
          TotalWins: int
          TotalLosses: int
          TotalMatches: int }

    type LeaderboardResponse =
        { Entries: LeaderboardEntry list
          HasMore: bool }

    type ErrorBody =
        { Code: string
          Message: string }

    type ErrorResponse =
        { Error: ErrorBody }

    type HealthResponse =
        { Status: string }


    let private usernameRegex = System.Text.RegularExpressions.Regex(@"^[a-zA-Z0-9 ]{3,20}$")

    let validateUsername (username: string) : Result<string, string> =
        let trimmed = username.Trim()
        if usernameRegex.IsMatch(trimmed) then
            Ok trimmed
        else
            Error "Username must be 3-20 alphanumeric characters (spaces allowed)"

    let toUserResponse (user: User) : UserResponse =
        { Id = user.Id
          Username = user.Username
          AvatarUrl = user.AvatarUrl
          IsAnonymous = user.IsAnonymous
          RngScore = user.RngScore
          TotalWins = user.TotalWins
          TotalLosses = user.TotalLosses
          TotalMatches = user.TotalMatches }
