using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

// A local contract simulator. No provider SDKs, HTTP clients or real transactions.
public sealed class MockIntegrationProviders(Db db, JsonObject spec) {
    private JsonArray Providers => spec["externalIntegrations"]?.AsArray() ?? new JsonArray();

    public static void Map(WebApplication app) {
        app.MapGet("/api/integrations", (MockIntegrationProviders mocks) => Results.Json(new {mode="mock",providers=mocks.Providers}));
        app.MapPost("/api/integrations/{providerId}/{operationId}", async Task<IResult>
            (HttpContext c,string providerId,string operationId,JsonElement body,MockIntegrationProviders mocks) => {
                var result=await mocks.CallCore(c,providerId,operationId,body,"contract");
                return Results.Json(result.Body,statusCode:result.StatusCode);
            });
        app.MapGet("/api/integrations/calls/{providerId}/{operationId}/{requestId}", async Task<IResult>
            (HttpContext c,string providerId,string operationId,string requestId,MockIntegrationProviders mocks) => {
                var row=await mocks.Get(c.Items["actor"]!.ToString()!,providerId,operationId,requestId);
                return row is null ? Results.NotFound() : Results.Json(row["response"]);
            });
        app.MapGet("/api/integrations/usage", async Task<IResult> (HttpContext c,MockIntegrationProviders mocks) => {
            if(c.Items["role"]?.ToString()!="admin") return Results.StatusCode(403);
            return Results.Json(await mocks.Usage());
        });
    }

    // Generated business handlers call this method using DI. Always inspect StatusCode.
    public Task<MockIntegrationResult> Call(HttpContext context,string providerId,string operationId,JsonElement request)
        => CallCore(context,providerId,operationId,request,"business");

    private Task<JsonNode?> Usage() => db.Node("SELECT coalesce(jsonb_object_agg(provider_id,jsonb_build_object('success',success,'failure',failure)),'{}'::jsonb) FROM (SELECT provider_id,count(*) FILTER(WHERE status_code=200) AS success,count(*) FILTER(WHERE status_code IN (402,422,503)) AS failure FROM mock_integration_calls WHERE origin='business' GROUP BY provider_id) counts");

    private Task<JsonNode?> Get(string actor,string provider,string operation,string requestId,string payload="null")
        => db.Node("SELECT jsonb_build_object('matches',request_payload=@payload::jsonb,'response',response_payload,'statusCode',status_code,'origin',origin) FROM mock_integration_calls WHERE actor=@actor AND provider_id=@provider AND operation_id=@operation AND request_id=@request",
            ("actor",actor),("provider",provider),("operation",operation),("request",requestId),("payload",payload));

    private async Task<MockIntegrationResult> CallCore(HttpContext context,string providerId,string operationId,JsonElement body,string origin) {
        MockIntegrationResult Error(int status,string message) => new(status,new JsonObject {["mode"]="mock",["error"]=message});
        var provider=Providers.FirstOrDefault(p=>p?["id"]?.ToString()==providerId);
        var operation=provider?["operations"]?.AsArray().FirstOrDefault(o=>o?["id"]?.ToString()==operationId);
        if(operation is null) return Error(404,"Unknown mock provider or operation");
        var actor=context.Items["actor"]?.ToString();
        if(string.IsNullOrEmpty(actor)) return Error(401,"Demo identity required");
        if(body.ValueKind!=JsonValueKind.Object || !body.TryGetProperty("requestId",out var requestValue) ||
            requestValue.ValueKind!=JsonValueKind.String || string.IsNullOrWhiteSpace(requestValue.GetString()) || requestValue.GetString()!.Length>100 ||
            !body.TryGetProperty("input",out var input) || input.ValueKind!=JsonValueKind.Object)
            return Error(400,"requestId:string and input:object required");
        var requestId=requestValue.GetString()!;
        var scenario="success";
        if(body.TryGetProperty("scenario",out var scenarioValue)) {
            if(scenarioValue.ValueKind!=JsonValueKind.String) return Error(400,"Invalid mock scenario");
            scenario=scenarioValue.GetString()!;
        }
        if(scenario is not ("success" or "declined" or "unavailable")) return Error(400,"Unknown mock scenario");
        var fields=operation["inputFields"]!.AsArray();
        foreach(var property in input.EnumerateObject())
            if(!fields.Any(f=>f!["name"]!.ToString()==property.Name)) return Error(400,"Unknown input: "+property.Name);
        foreach(var field in fields) {
            var name=field!["name"]!.ToString();var required=field["required"]!.GetValue<bool>();
            if(!input.TryGetProperty(name,out var value) || value.ValueKind==JsonValueKind.Null) {
                if(required) return Error(400,"Required input: "+name);
                continue;
            }
            var valid=field["type"]!.ToString() switch {
                "string"=>value.ValueKind==JsonValueKind.String && value.GetString()!.Length<=4000 && (!required || !string.IsNullOrWhiteSpace(value.GetString())),
                "integer"=>value.ValueKind==JsonValueKind.Number && value.TryGetInt64(out _),
                "number"=>value.ValueKind==JsonValueKind.Number && value.TryGetDecimal(out _),
                "boolean"=>value.ValueKind is JsonValueKind.True or JsonValueKind.False,
                "datetime"=>value.ValueKind==JsonValueKind.String && DateTimeOffset.TryParse(value.GetString(),CultureInfo.InvariantCulture,DateTimeStyles.None,out _),
                _=>false
            };
            if(!valid) return Error(400,"Invalid input: "+name);
        }
        if(provider!["kind"]!.ToString()=="payment") {
            if(!input.TryGetProperty("amount",out var amount) || !amount.TryGetDecimal(out var amountValue) || amountValue<=0 ||
                !input.TryGetProperty("currency",out var currency) || currency.ValueKind!=JsonValueKind.String ||
                !System.Text.RegularExpressions.Regex.IsMatch(currency.GetString()??"","^[A-Z]{3}$"))
                return Error(400,"Positive amount and three-letter currency required");
        }
        var payload=JsonSerializer.Serialize(new {input,scenario});
        var data=scenario=="success" ? operation["response"]!.DeepClone().AsObject() : new JsonObject();
        if(scenario=="success" && provider["kind"]!.ToString()=="payment") {
            data["amount"]=JsonNode.Parse(input.GetProperty("amount").GetRawText());
            data["currency"]=input.GetProperty("currency").GetString();
        }
        var status=scenario=="unavailable" ? 503 : scenario=="declined" ? (provider["kind"]!.ToString()=="payment"?402:422) : 200;
        var response=new JsonObject {
            ["mode"]="mock",["providerId"]=providerId,["operationId"]=operationId,["requestId"]=requestId,
            ["receiptId"]=Guid.NewGuid().ToString(),["scenario"]=scenario,["success"]=scenario=="success",
            ["data"]=data,["error"]=scenario=="success"?null:"mock_"+scenario,["createdAt"]=DateTimeOffset.UtcNow.ToString("O")
        };
        await db.Execute("INSERT INTO mock_integration_calls(actor,provider_id,operation_id,request_id,request_payload,response_payload,status_code,origin) VALUES(@actor,@provider,@operation,@request,@payload::jsonb,@response::jsonb,@status,@origin) ON CONFLICT(actor,provider_id,operation_id,request_id) DO NOTHING",
            ("actor",actor),("provider",providerId),("operation",operationId),("request",requestId),
            ("payload",payload),("response",response.ToJsonString()),("status",status),("origin",origin));
        var saved=await Get(actor,providerId,operationId,requestId,payload) ?? throw new InvalidOperationException("Missing persisted mock receipt");
        if(!saved["matches"]!.GetValue<bool>() || saved["origin"]!.ToString()!=origin)
            return Error(409,"requestId already used for another request");
        return new(saved["statusCode"]!.GetValue<int>(),saved["response"]!.DeepClone());
    }
}

public sealed record MockIntegrationResult(int StatusCode,JsonNode Body);
