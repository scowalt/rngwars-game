namespace RNGWars.Tests

open System.Collections.Concurrent
open System.Threading.Tasks
open Xunit
open RNGWars

[<CollectionDefinition("Matchmaking queue", DisableParallelization = true)>]
type MatchmakingQueueCollection() = class end

[<Collection("Matchmaking queue")>]
type MatchmakingQueueTests() =
    let pairs = ConcurrentQueue<string * string * string * string>()

    do
        MatchmakingQueue.clear ()
        MatchmakingQueue.setPairedHandler (fun p1 c1 p2 c2 -> pairs.Enqueue((p1, c1, p2, c2)))

    [<Fact>]
    let ``Two queued players are paired with their connections`` () =
        MatchmakingQueue.enqueue "alice" "conn-a"
        MatchmakingQueue.enqueue "bob" "conn-b"
        Assert.Equal<(string * string * string * string) list>([ ("alice", "conn-a", "bob", "conn-b") ], List.ofSeq pairs)

    [<Fact>]
    let ``Player who left and rejoined is not paired with themselves`` () =
        MatchmakingQueue.enqueue "alice" "conn-a"
        MatchmakingQueue.dequeue "alice"
        MatchmakingQueue.enqueue "alice" "conn-a"
        Assert.Empty(pairs)

        MatchmakingQueue.enqueue "bob" "conn-b"
        Assert.Equal<(string * string * string * string) list>([ ("alice", "conn-a", "bob", "conn-b") ], List.ofSeq pairs)

    [<Fact>]
    let ``Disconnected player is removed and can queue again from a new connection`` () =
        MatchmakingQueue.enqueue "alice" "conn-a1"
        MatchmakingQueue.removeConnection "conn-a1"
        MatchmakingQueue.enqueue "bob" "conn-b"
        Assert.Empty(pairs)

        MatchmakingQueue.enqueue "alice" "conn-a2"
        Assert.Equal<(string * string * string * string) list>([ ("bob", "conn-b", "alice", "conn-a2") ], List.ofSeq pairs)

    [<Fact>]
    let ``Requeueing from a new connection replaces the old one`` () =
        MatchmakingQueue.enqueue "alice" "conn-a1"
        MatchmakingQueue.enqueue "alice" "conn-a2"
        MatchmakingQueue.enqueue "bob" "conn-b"
        Assert.Equal<(string * string * string * string) list>([ ("alice", "conn-a2", "bob", "conn-b") ], List.ofSeq pairs)

    [<Fact>]
    let ``Concurrent joins pair everyone`` () =
        Parallel.For(0, 200, fun i -> MatchmakingQueue.enqueue $"user-{i}" $"conn-{i}") |> ignore
        Assert.Equal(100, pairs.Count)
        let paired = pairs |> Seq.collect (fun (p1, _, p2, _) -> [ p1; p2 ]) |> Set.ofSeq
        Assert.Equal(200, paired.Count)
