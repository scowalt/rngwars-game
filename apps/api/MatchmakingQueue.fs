namespace RNGWars

open System.Collections.Generic

module MatchmakingQueue =

    type QueueEntry =
        { UserId: string
          ConnectionId: string }

    let private gate = obj ()
    let private waiting = List<QueueEntry>()
    let mutable private onPaired: (string -> string -> string -> string -> unit) option = None

    let setPairedHandler (handler: string -> string -> string -> string -> unit) =
        onPaired <- Some handler

    let enqueue (userId: string) (connectionId: string) : unit =
        let pair =
            lock gate (fun () ->
                waiting.RemoveAll(fun e -> e.UserId = userId) |> ignore
                let entry = { UserId = userId; ConnectionId = connectionId }

                if waiting.Count > 0 then
                    let opponent = waiting[0]
                    waiting.RemoveAt(0)
                    Some(opponent, entry)
                else
                    waiting.Add(entry)
                    None)

        match pair, onPaired with
        | Some(p1, p2), Some handler -> handler p1.UserId p1.ConnectionId p2.UserId p2.ConnectionId
        | _ -> ()

    let dequeue (userId: string) : unit =
        lock gate (fun () -> waiting.RemoveAll(fun e -> e.UserId = userId) |> ignore)

    let removeConnection (connectionId: string) : unit =
        lock gate (fun () -> waiting.RemoveAll(fun e -> e.ConnectionId = connectionId) |> ignore)

    let clear () : unit =
        lock gate (fun () -> waiting.Clear())
