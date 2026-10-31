using System.Text.Json.Nodes;

public static class GeneratedExtensions
{
    public static void Map(WebApplication app)
    {
        app.MapGet("/api/generated/status", async Task<IResult> (HttpContext context, Db db) =>
        {
            var actor = context.Items["actor"] as string;
            if (string.IsNullOrEmpty(actor)) return Results.Unauthorized();
            var session = await db.Node(
                "SELECT jsonb_build_object('id',id,'zoneId',zone_id,'expiresAt',expires_at," +
                "'remainingSeconds',greatest(0,extract(epoch FROM (expires_at-now())))::int) " +
                "FROM parking_sessions WHERE actor=@actor AND ended_at IS NULL", ("actor", actor));
            var events = await db.Node(
                "SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'kind',kind,'message',message," +
                "'fromZone',from_zone,'toZone',to_zone,'recordedAt',recorded_at) ORDER BY id DESC),'[]'::jsonb) " +
                "FROM parking_events WHERE actor=@actor", ("actor", actor));
            return Results.Json(new JsonObject
            {
                ["session"] = session,
                ["events"] = events ?? new JsonArray()
            });
        });
    }
}
