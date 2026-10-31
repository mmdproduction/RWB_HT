using System.Text.Json;
using System.Text.Json.Nodes;
using Npgsql;

public static class Parking {
    const string Now="coalesce((SELECT value FROM demo_clock WHERE id=1),now())";
    static string Actor(HttpContext c)=>c.Items["actor"]!.ToString()!;
    static bool Admin(HttpContext c)=>c.Items["role"]?.ToString()=="admin";
    static bool Driver(HttpContext c)=>c.Items["role"]?.ToString() is "driver" or "admin";
    static async Task Sweep(Db db) {
        await db.Execute($"UPDATE parking_sessions SET ended_at=expires_at,end_reason='expired' WHERE ended_at IS NULL AND expires_at<={Now}");
        await db.Execute($"WITH due AS (UPDATE parking_sessions SET warning_emitted=true WHERE ended_at IS NULL AND NOT warning_emitted AND expires_at<={Now}+interval '10 minutes' RETURNING id,actor,zone_id) INSERT INTO parking_events(actor,kind,message,from_zone,to_zone,session_id,recorded_at) SELECT actor,'expiry_warning','До конца оплаченного времени осталось не более 10 минут',zone_id,zone_id,id,{Now} FROM due");
    }
    static string SessionJson => $"jsonb_build_object('id',s.id,'zoneId',s.zone_id,'startedAt',s.started_at,'expiresAt',s.expires_at,'endedAt',s.ended_at,'endReason',s.end_reason,'cost',s.cost,'warning',s.warning_emitted,'remainingSeconds',greatest(0,extract(epoch FROM (s.expires_at-{Now})))::int,'zoneMismatch',s.zone_id IS DISTINCT FROM (SELECT zone_id FROM parking_positions WHERE actor=s.actor ORDER BY id DESC LIMIT 1))";
    public static void Map(WebApplication app,Db db) {
        app.MapGet("/api/parking/zones",async ()=>Results.Json(await db.Node("SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'name',name,'rate',rate,'geometry',ST_AsGeoJSON(boundary)::jsonb) ORDER BY id),'[]'::jsonb) FROM parking_zones")));
        app.MapPost("/api/parking/zones",async Task<IResult> (HttpContext c,JsonElement body)=> {
            if(!Admin(c)) return Results.StatusCode(403);
            if(!body.TryGetProperty("id",out var id)||id.ValueKind!=JsonValueKind.String||!System.Text.RegularExpressions.Regex.IsMatch(id.GetString()!,"^[A-Za-z0-9_-]{1,40}$") || !body.TryGetProperty("name",out var name)||name.ValueKind!=JsonValueKind.String||string.IsNullOrWhiteSpace(name.GetString())||name.GetString()!.Length>200 || !body.TryGetProperty("rate",out var rate)||!rate.TryGetDecimal(out var amount)||amount<0||amount>100000 || !body.TryGetProperty("coordinates",out var coordinates)||coordinates.ValueKind!=JsonValueKind.Array||coordinates.GetArrayLength()<4||coordinates.GetArrayLength()>1000) return Results.BadRequest(new {error="id, name, nonnegative rate and closed coordinates required"});
            foreach(var point in coordinates.EnumerateArray()) if(point.ValueKind!=JsonValueKind.Array||point.GetArrayLength()!=2||!point[0].TryGetDouble(out var lon)||!point[1].TryGetDouble(out var lat)||lon < -180||lon>180||lat < -90||lat>90) return Results.BadRequest(new {error="Invalid coordinates"});
            if(coordinates[0].GetRawText()!=coordinates[coordinates.GetArrayLength()-1].GetRawText()) return Results.BadRequest(new {error="Polygon must be closed"});
            var geo="{\"type\":\"Polygon\",\"coordinates\":["+coordinates.GetRawText()+"]}";
            var valid=await db.Node("SELECT to_jsonb(ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON(@geo),4326)))",("geo",geo));
            if(valid?.GetValue<bool>()!=true) return Results.BadRequest(new {error="Invalid polygon"});
            await db.Execute("INSERT INTO parking_zones(id,name,rate,boundary) VALUES(@id,@name,@rate,ST_SetSRID(ST_GeomFromGeoJSON(@geo),4326)) ON CONFLICT(id) DO UPDATE SET name=excluded.name,rate=excluded.rate,boundary=excluded.boundary",("id",id.GetString()),("name",name.GetString()),("rate",amount),("geo",geo));
            return Results.Ok(new {id=id.GetString()});
        });
        app.MapPost("/api/parking/position",async Task<IResult> (HttpContext c,JsonElement body)=> {
            if(!Driver(c)) return Results.StatusCode(403);
            if(!body.TryGetProperty("longitude",out var lonValue)||!lonValue.TryGetDouble(out var lon)||!body.TryGetProperty("latitude",out var latValue)||!latValue.TryGetDouble(out var lat)||!double.IsFinite(lon)||!double.IsFinite(lat)||lon < -180||lon>180||lat < -90||lat>90) return Results.BadRequest(new {error="Valid longitude/latitude required"});
            var actor=Actor(c);
            await using var connection=await db.Open(); await using var tx=await connection.BeginTransactionAsync();
            async Task<object?> Scalar(string sql,params (string,object?)[] values) { await using var cmd=Db.Command(connection,tx,sql,values); return await cmd.ExecuteScalarAsync(); }
            await Scalar("SELECT pg_advisory_xact_lock(hashtext(@actor))",("actor",actor));
            var previous=(await Scalar("SELECT zone_id FROM parking_positions WHERE actor=@actor ORDER BY id DESC LIMIT 1",("actor",actor)))?.ToString();
            var zone=(await Scalar("SELECT id FROM parking_zones WHERE ST_Covers(boundary,ST_SetSRID(ST_Point(@lon,@lat),4326)) ORDER BY id LIMIT 1",("lon",lon),("lat",lat)))?.ToString();
            if(string.IsNullOrEmpty(zone)) zone=null;
            if(string.IsNullOrEmpty(previous)) previous=null;
            await Scalar($"INSERT INTO parking_positions(actor,location,zone_id,recorded_at) VALUES(@actor,ST_SetSRID(ST_Point(@lon,@lat),4326),@zone,{Now}) RETURNING id",("actor",actor),("lon",lon),("lat",lat),("zone",zone));
            var transition=previous==zone ? "unchanged" : zone is null ? "left_zone" : previous is null ? "entered_zone" : "zone_changed";
            if(transition!="unchanged") await Scalar($"INSERT INTO parking_events(actor,kind,message,from_zone,to_zone,recorded_at) VALUES(@actor,@kind,'Местоположение изменилось. Проверьте необходимость новой оплаты; действующая сессия сохранена.',@previous,@zone,{Now}) RETURNING id",("actor",actor),("kind",transition),("previous",previous),("zone",zone));
            await tx.CommitAsync();
            await Sweep(db);
            return Results.Ok(new {zoneId=zone,transition,paymentAdvice=transition!="unchanged"});
        });
        app.MapPost("/api/parking/sessions",async Task<IResult> (HttpContext c,JsonElement body)=> {
            if(!Driver(c)) return Results.StatusCode(403);
            if(!body.TryGetProperty("zoneId",out var zone)||zone.ValueKind!=JsonValueKind.String||!body.TryGetProperty("durationMinutes",out var duration)||!duration.TryGetInt32(out var minutes)||minutes<15||minutes>1440||!body.TryGetProperty("confirmDemoPayment",out var confirm)||confirm.ValueKind!=JsonValueKind.True) return Results.BadRequest(new {error="zoneId, durationMinutes (15..1440), confirmDemoPayment=true required. Demo only; no funds charged."});
            await Sweep(db);
            var actor=Actor(c);
            var position=await db.Node("SELECT jsonb_build_object('zoneId',zone_id) FROM parking_positions WHERE actor=@actor ORDER BY id DESC LIMIT 1",("actor",actor));
            if(position?["zoneId"]?.ToString()!=zone.GetString()) return Results.BadRequest(new {error="Confirm a session in the current position zone"});
            var id=Guid.NewGuid();
            var count=await db.Execute($"INSERT INTO parking_sessions(id,actor,zone_id,started_at,expires_at,cost) SELECT @id,@actor,id,{Now},{Now}+make_interval(mins=>@minutes),round(rate*@minutes/60,2) FROM parking_zones WHERE id=@zone",("id",id),("actor",actor),("minutes",minutes),("zone",zone.GetString()));
            if(count==0) return Results.NotFound();
            await db.Execute($"INSERT INTO parking_events(actor,kind,message,to_zone,session_id,recorded_at) VALUES(@actor,'session_started','Демонстрационная оплата подтверждена: реальные деньги не списываются',@zone,@id,{Now})",("actor",actor),("zone",zone.GetString()),("id",id));
            return Results.Created($"/api/parking/sessions/{id}",new {id,zoneId=zone.GetString(),demoPayment=true});
        });
        app.MapGet("/api/parking/active",async (HttpContext c)=> {
            await Sweep(db);
            var session=await db.Node($"SELECT {SessionJson} FROM parking_sessions s WHERE actor=@actor AND ended_at IS NULL",("actor",Actor(c)));
            var position=await db.Node("SELECT jsonb_build_object('longitude',ST_X(location),'latitude',ST_Y(location),'zoneId',zone_id,'recordedAt',recorded_at) FROM parking_positions WHERE actor=@actor ORDER BY id DESC LIMIT 1",("actor",Actor(c)));
            return Results.Ok(new {session,position});
        });
        app.MapPost("/api/parking/sessions/{id:guid}/stop",async Task<IResult> (HttpContext c,Guid id)=> {
            if(!Driver(c)) return Results.StatusCode(403);
            var count=await db.Execute($"UPDATE parking_sessions SET ended_at=least(expires_at,{Now}),end_reason='driver' WHERE id=@id AND actor=@actor AND ended_at IS NULL",("id",id),("actor",Actor(c)));
            return count==0 ? Results.NotFound() : Results.Ok(new {id,stopped=true});
        });
        app.MapGet("/api/parking/history",async (HttpContext c)=> {
            await Sweep(db);
            return Results.Json(await db.Node($"SELECT coalesce(jsonb_agg({SessionJson} ORDER BY s.started_at DESC),'[]'::jsonb) FROM parking_sessions s WHERE actor=@actor AND ended_at IS NOT NULL",("actor",Actor(c))));
        });
        app.MapGet("/api/parking/events",async Task<IResult> (HttpContext c)=>Results.Json(await db.Node("SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY id),'[]'::jsonb) FROM (SELECT id,kind,message,from_zone AS \"fromZone\",to_zone AS \"toZone\",session_id AS \"sessionId\",recorded_at AS \"recordedAt\" FROM parking_events WHERE actor=@actor ORDER BY id DESC LIMIT 200) e",("actor",Actor(c)))));
        app.MapPost("/api/parking/clock",async Task<IResult> (HttpContext c,JsonElement body)=> {
            if(!Admin(c)) return Results.StatusCode(403);
            if(Environment.GetEnvironmentVariable("TEST_CLOCK_ENABLED")!="true") return Results.NotFound();
            if(!body.TryGetProperty("advanceSeconds",out var value)||!value.TryGetInt32(out var seconds)||seconds<0||seconds>86400) return Results.BadRequest(new {error="advanceSeconds must be 0..86400"});
            var result=await db.Node("INSERT INTO demo_clock(id,value) VALUES(1,now()+make_interval(secs=>@seconds)) ON CONFLICT(id) DO UPDATE SET value=demo_clock.value+make_interval(secs=>@seconds) RETURNING jsonb_build_object('now',value,'controlled',true)",("seconds",seconds));
            await Sweep(db); return Results.Json(result);
        });
    }
}
