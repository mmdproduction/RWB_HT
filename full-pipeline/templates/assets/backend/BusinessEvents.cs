using Confluent.Kafka;
using Confluent.Kafka.Admin;
using Npgsql;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

// Trusted internal transport. Generated handlers only enqueue in their business transaction.
public sealed class BusinessEvents(Db db) {
    public const string Topic = "app.business.v1";
    public static string Bootstrap => Environment.GetEnvironmentVariable("KAFKA_BOOTSTRAP_SERVERS") ?? "kafka:9092";
    public static readonly JsonObject Contract = JsonNode.Parse(File.ReadAllText("event-contract.json"))!.AsObject();
    public static JsonNode Definition(string endpointId) => Contract["events"]!.AsArray()
        .FirstOrDefault(e => e!["endpointId"]!.ToString() == endpointId)
        ?? throw new InvalidOperationException("Endpoint has no frozen Kafka contract: " + endpointId);

    public async Task<Guid> Enqueue(NpgsqlConnection connection, NpgsqlTransaction transaction,
        HttpContext context, string endpointId, string businessKey, int responseStatus, JsonNode? result) {
        var definition = Definition(endpointId);
        if (!definition["successfulStatuses"]!.AsArray().Any(s => s!.GetValue<int>() == responseStatus))
            throw new InvalidOperationException("Kafka event requires a successful planned status");
        if (context.GetEndpoint() is null || !context.Request.Path.StartsWithSegments("/api/generated"))
            throw new InvalidOperationException("Events can only originate in a business handler");
        var route = Regex.Replace(Regex.Escape(definition["path"]!.ToString()), @"\\\{[A-Za-z][A-Za-z0-9_]*}", "[^/]+");
        if (context.Request.Method != definition["method"]!.ToString() || !Regex.IsMatch(context.Request.Path.Value!, "^" + route + "$"))
            throw new InvalidOperationException("Kafka endpointId does not match the actual business route");
        if (string.IsNullOrWhiteSpace(businessKey) || businessKey.Length > 200)
            throw new InvalidOperationException("Use a stable business key of 1..200 characters");
        var actor = context.Items["actor"]?.ToString() ?? throw new InvalidOperationException("Authenticated actor missing");
        var id = Guid.NewGuid();
        var envelope = new JsonObject {
            ["schemaVersion"] = 1, ["eventId"] = id.ToString(), ["topic"] = Topic,
            ["eventType"] = definition["eventType"]!.ToString(), ["endpointId"] = endpointId,
            ["businessKey"] = businessKey, ["actor"] = actor,
            ["occurredAt"] = DateTimeOffset.UtcNow.ToString("O"), ["responseStatus"] = responseStatus,
            ["requirementIds"] = definition["requirementIds"]!.DeepClone(), ["data"] = result?.DeepClone()
        };
        var encoded = envelope.ToJsonString();
        if (System.Text.Encoding.UTF8.GetByteCount(encoded) > 262144) throw new InvalidOperationException("Event exceeds 256KB");
        await using (var command = Db.Command(connection, transaction,
            "INSERT INTO business_outbox(event_id,actor,endpoint_id,business_key,envelope) VALUES(@id,@actor,@endpoint,@key,@body::jsonb) ON CONFLICT(actor,endpoint_id,business_key) DO NOTHING",
            ("id",id),("actor",actor),("endpoint",endpointId),("key",businessKey),("body",encoded)))
            await command.ExecuteNonQueryAsync(context.RequestAborted);
        await using (var command = Db.Command(connection, transaction,
            "SELECT envelope::text FROM business_outbox WHERE actor=@actor AND endpoint_id=@endpoint AND business_key=@key",
            ("actor",actor),("endpoint",endpointId),("key",businessKey))) {
            var saved = JsonNode.Parse((string)(await command.ExecuteScalarAsync(context.RequestAborted))!)!;
            if (!JsonNode.DeepEquals(saved["data"],result) || saved["responseStatus"]!.GetValue<int>() != responseStatus)
                throw new BadHttpRequestException("Business key already used with a different event result",409);
            id = Guid.Parse(saved["eventId"]!.ToString());
        }
        // Header is emitted only on a successful HTTP response, after the handler commits.
        context.Response.OnStarting(() => {
            if (context.Response.StatusCode is >=200 and <300) context.Response.Headers["X-Business-Event-Id"] = id.ToString();
            return Task.CompletedTask;
        });
        return id;
    }

    public static void Map(WebApplication app, Db db) {
        app.MapGet("/api/events/state", async (HttpContext context) => Results.Json(await db.Node(
            "SELECT jsonb_build_object('enqueued',count(*)) FROM business_outbox WHERE actor=@actor",
            ("actor",context.Items["actor"]!.ToString()))));
        app.MapGet("/api/events/activity", async (HttpContext context) => Results.Json(await db.Node(
            "SELECT coalesce(jsonb_agg(item ORDER BY processed_at DESC),'[]'::jsonb) FROM (SELECT processed_at,jsonb_build_object('eventId',event_id,'endpointId',endpoint_id,'label',label,'businessKey',business_key,'occurredAt',occurred_at,'processedAt',processed_at) item FROM business_activity WHERE actor=@actor ORDER BY processed_at DESC LIMIT 30) items",
            ("actor",context.Items["actor"]!.ToString()))));
        app.MapGet("/api/events/evidence/{id:guid}", async Task<IResult> (HttpContext context,Guid id) => {
            var row = await db.Node("""
                SELECT jsonb_build_object('envelope',o.envelope,'publishedAt',o.published_at,
                  'partition',o.kafka_partition,'offset',o.kafka_offset,'processedAt',i.processed_at,
                  'consumerPartition',i.kafka_partition,'consumerOffset',i.kafka_offset,
                  'deliveries',i.deliveries,'lastConsumerOffset',i.last_kafka_offset,
                  'activityCount',(SELECT count(*) FROM business_activity a WHERE a.event_id=o.event_id))
                FROM business_outbox o LEFT JOIN business_inbox i USING(event_id)
                WHERE o.event_id=@id AND o.actor=@actor
                """,("id",id),("actor",context.Items["actor"]!.ToString()));
            return row is null ? Results.NotFound() : Results.Json(row);
        });
        // Explicit demo-only recovery hook. Cannot create/alter events; enabled only in disposable acceptance.
        app.MapPost("/api/events/replay/{id:guid}", async Task<IResult> (HttpContext context,Guid id) => {
            if (Environment.GetEnvironmentVariable("TEST_CLOCK_ENABLED") != "true" || context.Items["role"]?.ToString() != "admin") return Results.StatusCode(403);
            var changed = await db.Execute("UPDATE business_outbox SET published_at=NULL WHERE event_id=@id",("id",id));
            return changed == 0 ? Results.NotFound() : Results.Ok(new { replayQueued = true });
        });
    }
}

public static class KafkaTopic {
    public static async Task Ensure(CancellationToken token) {
        using var admin = new AdminClientBuilder(new AdminClientConfig { BootstrapServers = BusinessEvents.Bootstrap, SocketTimeoutMs = 10000 }).Build();
        for (var attempt = 0; ; attempt++) {
            try {
                await admin.CreateTopicsAsync(new[] { new TopicSpecification { Name = BusinessEvents.Topic, NumPartitions = 1, ReplicationFactor = 1 } },
                    new CreateTopicsOptions { RequestTimeout = TimeSpan.FromSeconds(10) });
                return;
            } catch (CreateTopicsException error) when (error.Results.All(r => r.Error.Code == ErrorCode.TopicAlreadyExists)) { return; }
            catch (KafkaException) when (attempt < 9) { await Task.Delay(2000,token); }
        }
    }
}

public sealed class OutboxPublisher(Db db, ILogger<OutboxPublisher> log) : BackgroundService {
    protected override async Task ExecuteAsync(CancellationToken token) {
        await KafkaTopic.Ensure(token);
        using var producer = new ProducerBuilder<string,string>(new ProducerConfig {
            BootstrapServers = BusinessEvents.Bootstrap, EnableIdempotence = true, Acks = Acks.All,
            MessageTimeoutMs = 15000, ClientId = "business-outbox", AllowAutoCreateTopics = false
        }).Build();
        while (!token.IsCancellationRequested) {
            try {
                // One transaction/row lock prevents concurrent publishers racing on the same outbox entry.
                await using var connection = await db.Open();
                await using var tx = await connection.BeginTransactionAsync(token);
                string? raw; Guid id;
                await using (var select = Db.Command(connection,tx,
                    "SELECT envelope::text FROM business_outbox WHERE published_at IS NULL ORDER BY created_at,event_id FOR UPDATE SKIP LOCKED LIMIT 1"))
                    raw = await select.ExecuteScalarAsync(token) as string;
                if (raw is null) { await tx.CommitAsync(token); await Task.Delay(250,token); continue; }
                var envelope = JsonNode.Parse(raw)!; id = Guid.Parse(envelope["eventId"]!.ToString());
                try {
                    var delivery = await producer.ProduceAsync(BusinessEvents.Topic,new Message<string,string> {
                        Key = envelope["actor"] + ":" + envelope["businessKey"], Value = raw },token);
                    await using var update = Db.Command(connection,tx,
                        "UPDATE business_outbox SET published_at=now(),attempts=attempts+1,last_error=NULL,kafka_partition=@partition,kafka_offset=@offset WHERE event_id=@id",
                        ("partition",delivery.Partition.Value),("offset",delivery.Offset.Value),("id",id));
                    await update.ExecuteNonQueryAsync(token);
                } catch (ProduceException<string,string> error) {
                    log.LogWarning("Kafka delivery pending for {EventId}: {Reason}",id,error.Error.Reason);
                    await using var update = Db.Command(connection,tx,
                        "UPDATE business_outbox SET attempts=attempts+1,last_error=@error WHERE event_id=@id",("id",id),("error",error.Error.Reason));
                    await update.ExecuteNonQueryAsync(token);
                }
                await tx.CommitAsync(token);
                await Task.Delay(250,token);
            } catch (OperationCanceledException) when (token.IsCancellationRequested) { break; }
            catch (Exception error) { log.LogError(error,"Outbox publisher retry"); await Task.Delay(2000,token); }
        }
        producer.Flush(TimeSpan.FromSeconds(5));
    }
}

public sealed class ActivityConsumer(Db db, ILogger<ActivityConsumer> log) : BackgroundService {
    private long lastPoll;
    public bool Healthy => DateTimeOffset.UtcNow.ToUnixTimeSeconds() - Interlocked.Read(ref lastPoll) < 20;
    protected override async Task ExecuteAsync(CancellationToken token) {
        await KafkaTopic.Ensure(token);
        using var consumer = new ConsumerBuilder<string,string>(new ConsumerConfig {
            BootstrapServers = BusinessEvents.Bootstrap, GroupId = "activity-v1", ClientId = "activity-consumer",
            AutoOffsetReset = AutoOffsetReset.Earliest, EnableAutoCommit = false,
            EnableAutoOffsetStore = false, AllowAutoCreateTopics = false
        }).Build();
        consumer.Subscribe(BusinessEvents.Topic);
        using var admin = new AdminClientBuilder(new AdminClientConfig { BootstrapServers = BusinessEvents.Bootstrap, SocketTimeoutMs = 5000 }).Build();
        try {
            while (!token.IsCancellationRequested) {
                try {
                    var message = consumer.Consume(TimeSpan.FromSeconds(1));
                    // Metadata readiness proves this process is polling the actual broker.
                    if (message is null) {
                        admin.GetMetadata(BusinessEvents.Topic,TimeSpan.FromSeconds(5));
                        Interlocked.Exchange(ref lastPoll,DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                        continue;
                    }
                    var envelope = JsonNode.Parse(message.Message.Value) ?? throw new InvalidOperationException("Empty event");
                    var id = Guid.Parse(envelope["eventId"]!.ToString());
                    var definition = BusinessEvents.Definition(envelope["endpointId"]!.ToString());
                    await using var connection = await db.Open();
                    await using var tx = await connection.BeginTransactionAsync(token);
                    await using (var select = Db.Command(connection,tx,"SELECT envelope::text FROM business_outbox WHERE event_id=@id",("id",id))) {
                        var saved = await select.ExecuteScalarAsync(token) as string;
                        if (saved is null || !JsonNode.DeepEquals(JsonNode.Parse(saved),envelope)) throw new InvalidOperationException("Event differs from committed outbox");
                    }
                    await using (var insert = Db.Command(connection,tx,"INSERT INTO business_inbox(event_id,kafka_partition,kafka_offset,last_kafka_offset) VALUES(@id,@partition,@offset,@offset) ON CONFLICT DO NOTHING",
                        ("id",id),("partition",message.Partition.Value),("offset",message.Offset.Value))) {
                        if (await insert.ExecuteNonQueryAsync(token) == 1) {
                            await using var activity = Db.Command(connection,tx,
                                "INSERT INTO business_activity(event_id,actor,endpoint_id,label,business_key,result,occurred_at) VALUES(@id,@actor,@endpoint,@label,@key,@data::jsonb,@occurred)",
                                ("id",id),("actor",envelope["actor"]!.ToString()),("endpoint",envelope["endpointId"]!.ToString()),
                                ("label",definition["label"]!.ToString()),("key",envelope["businessKey"]!.ToString()),
                                ("data",envelope["data"]?.ToJsonString() ?? "null"),("occurred",DateTimeOffset.Parse(envelope["occurredAt"]!.ToString()).UtcDateTime));
                            await activity.ExecuteNonQueryAsync(token);
                        } else {
                            await using var duplicate = Db.Command(connection,tx,"UPDATE business_inbox SET deliveries=deliveries+1,last_kafka_offset=greatest(last_kafka_offset,@offset) WHERE event_id=@id",("id",id),("offset",message.Offset.Value));
                            await duplicate.ExecuteNonQueryAsync(token);
                        }
                    }
                    await tx.CommitAsync(token);
                    // Database effect precedes offset commit. A crash may redeliver, inbox removes duplicates.
                    consumer.Commit(message);
                    Interlocked.Exchange(ref lastPoll,DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                } catch (OperationCanceledException) when (token.IsCancellationRequested) { break; }
                catch (Exception error) {
                    log.LogError(error,"Kafka consumer failed; restarting from committed offset");
                    // Exit instead of accidentally committing past a failed record. Compose restarts the process.
                    throw;
                }
            }
        } finally { consumer.Close(); }
    }
}
