using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 1048576);
var spec = JsonNode.Parse(File.ReadAllText("app-spec.json"))!.AsObject();
var source = NpgsqlDataSource.Create(Environment.GetEnvironmentVariable("DATABASE_URL") ?? throw new InvalidOperationException("DATABASE_URL missing"));
var db = new Db(source);
// Generated minimal API handlers may request Db/NpgsqlDataSource as services.
// Register before Build so ASP.NET does not infer Db as a JSON request body.
builder.Services.AddSingleton<NpgsqlDataSource>(source);
builder.Services.AddSingleton<Db>(db);
builder.Services.AddSingleton<MockIntegrationProviders>(new MockIntegrationProviders(db,spec));
builder.Services.AddSingleton<BusinessEvents>();
if (Environment.GetEnvironmentVariable("APP_MODE") == "consumer") {
    builder.Services.AddSingleton<ActivityConsumer>();
    builder.Services.AddHostedService(provider => provider.GetRequiredService<ActivityConsumer>());
    var consumerApp = builder.Build();
    consumerApp.MapGet("/health", async (ActivityConsumer consumer) => {
        await db.Execute("SELECT 1");
        return consumer.Healthy ? Results.Ok(new {status="ok",mode="consumer"}) : Results.StatusCode(503);
    });
    await consumerApp.RunAsync();
    return;
}
builder.Services.AddHostedService<OutboxPublisher>();
await db.Execute(File.ReadAllText("schema.sql"));
var roles = spec["roles"]!.AsArray().Select(x => x!.GetValue<string>()).Append("admin").Distinct().ToHashSet();
if (spec["requiresLogin"]?.GetValue<bool>()==false) roles.Add("user");
bool parking = spec["capabilities"]!.AsArray().Any(x => (x?.ToString() ?? "").Contains("parking", StringComparison.OrdinalIgnoreCase));
if (parking) roles.Add("driver");
var app = builder.Build();
app.Use(async (context, next) => {
    try {
        var path = context.Request.Path.Value ?? "";
        if (path.StartsWith("/api/",StringComparison.OrdinalIgnoreCase) && !path.Equals("/api/auth/login",StringComparison.OrdinalIgnoreCase) && !path.Equals("/api/schema",StringComparison.OrdinalIgnoreCase)) {
            var header = context.Request.Headers.Authorization.ToString();
            if (!header.StartsWith("Bearer ", StringComparison.Ordinal)) { context.Response.StatusCode = 401; return; }
            var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(header[7..])));
            var token = await db.Node("SELECT jsonb_build_object('role',role,'actor',actor) FROM demo_tokens WHERE token_hash=@hash AND expires_at>now()", ("hash",hash));
            if (token is null) { context.Response.StatusCode = 401; return; }
            context.Items["role"] = token["role"]!.ToString();
            context.Items["actor"] = token["actor"]!.ToString();
        }
        await next(context);
    } catch (BadHttpRequestException e) { context.Response.StatusCode=e.StatusCode; await context.Response.WriteAsJsonAsync(new {error=e.Message}); }
      catch (JsonException) { context.Response.StatusCode=400; await context.Response.WriteAsJsonAsync(new {error="Invalid JSON"}); }
      catch (PostgresException e) when (e.SqlState=="23505") { context.Response.StatusCode=409; await context.Response.WriteAsJsonAsync(new {error="Conflict"}); }
});
app.MapGet("/health", async () => { await db.Execute("SELECT 1"); return Results.Ok(new {status="ok"}); });
app.MapGet("/api/schema", () => Results.Json(spec));
app.MapGet("/api/health", async () => Results.Json(await db.Node("SELECT jsonb_build_object('postgres',current_setting('server_version'),'postgis',postgis_lib_version())")));
app.MapPost("/api/auth/login", async Task<IResult> (JsonElement body) => {
    if (!body.TryGetProperty("role",out var roleValue) || roleValue.ValueKind!=JsonValueKind.String || !roles.Contains(roleValue.GetString()!)) return Results.BadRequest(new {error="Unknown demo role"});
    var role = roleValue.GetString()!;
    var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(token)));
    await db.Execute("INSERT INTO demo_tokens(token_hash,role,actor,expires_at) VALUES(@hash,@role,@actor,now()+interval '12 hours')", ("hash",hash),("role",role),("actor","demo-"+role));
    return Results.Ok(new {token,role,demo=true});
});
JsonNode? Entity(string name) => spec["entities"]!.AsArray().FirstOrDefault(x => x!["name"]!.ToString()==name);
string? Validate(JsonNode entity, JsonElement body) {
    if(body.ValueKind!=JsonValueKind.Object) return "Expected JSON object";
    var fields=entity["fields"]!.AsArray();
    foreach(var property in body.EnumerateObject()) if(!fields.Any(f=>f!["name"]!.ToString()==property.Name)) return "Unknown field: "+property.Name;
    foreach(var field in fields) {
        var name=field!["name"]!.ToString();
        var required=field["required"]!.GetValue<bool>();
        bool present=body.TryGetProperty(name,out var value) && value.ValueKind!=JsonValueKind.Null;
        if(!present) { if(required) return "Required field: "+name; continue; }
        bool valid=field["type"]!.ToString() switch {
            "string" => value.ValueKind==JsonValueKind.String && value.GetString()!.Length<=4000 && (!required || !string.IsNullOrWhiteSpace(value.GetString())),
            "integer" => value.ValueKind==JsonValueKind.Number && value.TryGetInt64(out _),
            "number" => value.ValueKind==JsonValueKind.Number && value.TryGetDecimal(out _),
            "boolean" => value.ValueKind is JsonValueKind.True or JsonValueKind.False,
            "datetime" => value.ValueKind==JsonValueKind.String && DateTimeOffset.TryParse(value.GetString(),CultureInfo.InvariantCulture,DateTimeStyles.None,out _),
            _=>false
        };
        if(!valid) return "Invalid field: "+name;
    }
    return null;
}
app.MapGet("/api/entities/{entity}", async Task<IResult> (string entity) => {
    if(Entity(entity) is null) return Results.NotFound();
    return Results.Json(await db.Node("SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'entity',entity,'data',payload,'createdAt',created_at,'updatedAt',updated_at) ORDER BY created_at),'[]'::jsonb) FROM records WHERE entity=@entity", ("entity",entity)));
});
app.MapGet("/api/entities/{entity}/{id:guid}", async Task<IResult> (string entity, Guid id) => {
    if(Entity(entity) is null) return Results.NotFound();
    var row=await db.Node("SELECT jsonb_build_object('id',id,'entity',entity,'data',payload,'createdAt',created_at,'updatedAt',updated_at) FROM records WHERE entity=@entity AND id=@id",("entity",entity),("id",id));
    return row is null ? Results.NotFound() : Results.Json(row);
});
app.MapPost("/api/entities/{entity}", async Task<IResult> (HttpContext c,string entity,JsonElement body) => {
    if(c.Items["role"]?.ToString()!="admin") return Results.StatusCode(403);
    var schema=Entity(entity); if(schema is null) return Results.NotFound();
    var error=Validate(schema,body); if(error is not null) return Results.BadRequest(new {error});
    var id=Guid.NewGuid();
    await db.Execute("INSERT INTO records(id,entity,payload) VALUES(@id,@entity,@data::jsonb)",("id",id),("entity",entity),("data",body.GetRawText()));
    return Results.Created($"/api/entities/{entity}/{id}",new {id,entity,data=body});
});
app.MapPut("/api/entities/{entity}/{id:guid}", async Task<IResult> (HttpContext c,string entity,Guid id,JsonElement body) => {
    if(c.Items["role"]?.ToString()!="admin") return Results.StatusCode(403);
    var schema=Entity(entity); if(schema is null) return Results.NotFound();
    var error=Validate(schema,body); if(error is not null) return Results.BadRequest(new {error});
    var changed=await db.Execute("UPDATE records SET payload=@data::jsonb,updated_at=now() WHERE id=@id AND entity=@entity",("data",body.GetRawText()),("id",id),("entity",entity));
    return changed==0 ? Results.NotFound() : Results.Ok(new {id,entity,data=body});
});
app.MapDelete("/api/entities/{entity}/{id:guid}", async Task<IResult> (HttpContext c,string entity,Guid id) => {
    if(c.Items["role"]?.ToString()!="admin") return Results.StatusCode(403);
    if(Entity(entity) is null) return Results.NotFound();
    var changed=await db.Execute("DELETE FROM records WHERE id=@id AND entity=@entity",("id",id),("entity",entity));
    return changed==0 ? Results.NotFound() : Results.NoContent();
});
if(parking) Parking.Map(app,db);
MockIntegrationProviders.Map(app);
BusinessEvents.Map(app,db);
GeneratedExtensions.Map(app);
await app.RunAsync();

public sealed class Db(NpgsqlDataSource source) {
    public async Task<NpgsqlConnection> Open() => await source.OpenConnectionAsync();
    public static NpgsqlCommand Command(NpgsqlConnection connection,NpgsqlTransaction? tx,string sql,params (string,object?)[] values) {
        var command=new NpgsqlCommand(sql,connection,tx);
        foreach(var (name,value) in values) command.Parameters.AddWithValue(name,value??DBNull.Value);
        return command;
    }
    public async Task<int> Execute(string sql,params (string,object?)[] values) {
        await using var c=await Open(); await using var command=Command(c,null,sql,values); return await command.ExecuteNonQueryAsync();
    }
    public async Task<JsonNode?> Node(string sql,params (string,object?)[] values) {
        await using var c=await Open(); await using var command=Command(c,null,sql,values); var result=await command.ExecuteScalarAsync(); return result is null || result is DBNull ? null : JsonNode.Parse(result.ToString()!);
    }
}
