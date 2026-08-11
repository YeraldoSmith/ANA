/*
 * Independent ANA v0.1 Core node for Phase 7 conformance validation.
 *
 * This file uses only the RFCs and test vectors.  It has no dependency on the
 * Python ANA package, the Python nodes, or a JSON library.  The small JSON
 * reader/writer below was written for this node so canonical JSON behaviour is
 * explicit and can be audited by another implementer.
 */

import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class AnaV01Node {
    private static final String VERSION = "0.1";
    private static final String CHAIN_ID = "ana-core-chain";

    private AnaV01Node() {}

    public static void main(String[] args) throws IOException {
        if (args.length != 1) {
            fail("usage", "expected one operation");
        }
        String operation = args[0];
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        try {
            Object result = switch (operation) {
                case "canonicalize" -> canonical(parse(input));
                case "emit-envelope" -> emitEnvelope(asObject(parse(input), "request"));
                case "accept-envelope" -> acceptEnvelope(input);
                case "emit-state-delta" -> emitStateDelta(asObject(parse(input), "request"));
                case "validate-state-delta" -> validateStateDelta(asObject(parse(input), "request"));
                case "import-state-bundle" -> importStateBundle(asObject(parse(input), "state bundle"));
                default -> throw new ProtocolException("unknown_operation", operation);
            };
            System.out.print(result);
        } catch (ProtocolException error) {
            System.err.println("ERROR:" + error.code + ":" + error.getMessage());
            System.exit(2);
        }
    }

    private static String emitEnvelope(Map<String, Object> request) {
        Map<String, Object> envelope = asObject(required(request, "envelope"), "envelope");
        Map<String, Object> header = asObject(required(request, "envelope_frame"), "envelope_frame");
        validateEnvelope(envelope);
        String streamId = requiredString(header, "stream_id");
        if (!streamId.equals(envelope.get("task_id")) || !integer(header.get("sequence"), "sequence").equals(BigInteger.ZERO)) {
            throw new ProtocolException("invalid_sequence", "initial task frame requires task_id stream and sequence 0");
        }
        String messageId = requiredString(header, "message_id");
        Map<String, Object> frame = baseFrame(messageId, streamId, BigInteger.ZERO, "envelope", canonical(envelope));
        return canonical(frame);
    }

    private static String acceptEnvelope(String wire) {
        Map<String, Object> frame = parseCanonicalFrame(wire);
        validateFrameMetadata(frame, "envelope");
        if (!integer(frame.get("sequence"), "sequence").equals(BigInteger.ZERO)) {
            throw new ProtocolException("invalid_sequence", "initial envelope must have sequence 0");
        }
        Map<String, Object> envelope = parseCanonicalObject(requiredString(frame, "payload"), "envelope payload");
        validateEnvelope(envelope);
        if (!frame.get("stream_id").equals(envelope.get("task_id"))) {
            throw new ProtocolException("broken_causality", "task stream_id must equal envelope task_id");
        }
        return canonical(envelope);
    }

    private static String emitStateDelta(Map<String, Object> request) {
        Map<String, Object> envelope = asObject(required(request, "envelope"), "envelope");
        Map<String, Object> taskFrame = asObject(required(request, "task_frame"), "task_frame");
        Map<String, Object> stateHeader = asObject(required(request, "state_delta_frame"), "state_delta_frame");
        validateEnvelope(envelope);
        validateFrameMetadata(taskFrame, "envelope");
        if (!taskFrame.get("stream_id").equals(envelope.get("task_id"))) {
            throw new ProtocolException("broken_causality", "task frame does not belong to envelope task");
        }
        BigInteger taskSequence = integer(taskFrame.get("sequence"), "task sequence");
        String stateStream = requiredString(stateHeader, "stream_id");
        BigInteger stateSequence = integer(stateHeader.get("sequence"), "state sequence");
        if (!stateStream.equals(envelope.get("task_id")) || !stateSequence.equals(taskSequence.add(BigInteger.ONE))) {
            throw new ProtocolException("invalid_sequence", "state delta must immediately follow task frame");
        }
        String stateMessage = requiredString(stateHeader, "message_id");
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("event_id", "evt-" + envelope.get("task_id") + "-project-state");
        payload.put("stream_id", envelope.get("task_id"));
        payload.put("parent_event_id", taskFrame.get("message_id"));
        payload.put("sequence", stateSequence);
        payload.put("kind", "project_state.upsert");
        Map<String, Object> nested = new LinkedHashMap<>();
        nested.put("task_id", envelope.get("task_id"));
        nested.put("status", "routed");
        nested.put("required_capabilities", envelope.get("capabilities"));
        payload.put("payload", nested);
        return canonical(baseFrame(stateMessage, stateStream, stateSequence, "state_delta", canonical(payload)));
    }

    private static String validateStateDelta(Map<String, Object> request) {
        String wire = requiredString(request, "wire");
        String expectedStream = requiredString(request, "expected_stream_id");
        String previousMessage = requiredString(request, "previous_message_id");
        BigInteger previousSequence = integer(request.get("previous_sequence"), "previous_sequence");
        Map<String, Object> frame = parseCanonicalFrame(wire);
        validateFrameMetadata(frame, "state_delta");
        if (!frame.get("stream_id").equals(expectedStream)) {
            throw new ProtocolException("broken_causality", "state delta is in another stream");
        }
        BigInteger frameSequence = integer(frame.get("sequence"), "frame sequence");
        if (frameSequence.compareTo(previousSequence) <= 0) {
            throw new ProtocolException("invalid_sequence", "state delta sequence does not advance");
        }
        Map<String, Object> delta = parseCanonicalObject(requiredString(frame, "payload"), "state delta payload");
        validateStateDeltaPayload(delta, expectedStream, previousMessage, previousSequence);
        // RFC-0002 §8.1 shows one sequence value for a State Delta event and
        // its frame.  Phase 7 records this explicit equality clarification.
        if (!integer(delta.get("sequence"), "delta sequence").equals(frameSequence)) {
            throw new ProtocolException("invalid_sequence", "frame and State Delta sequence differ");
        }
        return canonical(delta);
    }

    private static String importStateBundle(Map<String, Object> bundle) {
        Object records = required(bundle, "memory_records");
        if (!(records instanceof List<?> list)) {
            throw new ProtocolException("invalid_memory", "memory_records must be an array");
        }
        for (Object item : list) {
            validateMemoryRecord(asObject(item, "memory record"));
        }
        if (!(required(bundle, "project_state") instanceof Map<?, ?>)) {
            throw new ProtocolException("invalid_project_state", "project_state must be an object");
        }
        if (!(required(bundle, "policy") instanceof Map<?, ?>)) {
            throw new ProtocolException("invalid_policy", "policy must be an object");
        }
        return canonical(bundle);
    }

    private static Map<String, Object> baseFrame(
        String messageId, String streamId, BigInteger sequence, String payloadType, String payload
    ) {
        Map<String, Object> frame = new LinkedHashMap<>();
        frame.put("protocol_version", VERSION);
        frame.put("chain_id", CHAIN_ID);
        frame.put("chain_version", VERSION);
        frame.put("dictionary_id", null);
        frame.put("dictionary_version", null);
        frame.put("message_id", messageId);
        frame.put("stream_id", streamId);
        frame.put("sequence", sequence);
        frame.put("payload_type", payloadType);
        frame.put("payload", payload);
        frame.put("transforms", List.of());
        return frame;
    }

    private static Map<String, Object> parseCanonicalFrame(String wire) {
        Map<String, Object> frame = parseCanonicalObject(wire, "wire frame");
        if (!canonical(frame).equals(wire)) {
            throw new ProtocolException("noncanonical", "wire frame is not canonical JSON");
        }
        return frame;
    }

    private static Map<String, Object> parseCanonicalObject(String text, String label) {
        Object value = parse(text);
        Map<String, Object> object = asObject(value, label);
        if (!canonical(object).equals(text)) {
            throw new ProtocolException("noncanonical", label + " is not canonical JSON");
        }
        return object;
    }

    private static void validateFrameMetadata(Map<String, Object> frame, String payloadType) {
        if (!VERSION.equals(frame.get("protocol_version")) || !CHAIN_ID.equals(frame.get("chain_id"))
            || !VERSION.equals(frame.get("chain_version")) || frame.get("dictionary_id") != null
            || frame.get("dictionary_version") != null || !(frame.get("transforms") instanceof List<?> transforms)
            || !transforms.isEmpty()) {
            throw new ProtocolException("unsupported_profile", "not ana-core-chain v0.1 canonical fallback");
        }
        if (!payloadType.equals(frame.get("payload_type"))) {
            throw new ProtocolException("unknown_required_semantics", "unsupported payload_type");
        }
        requiredString(frame, "message_id");
        requiredString(frame, "stream_id");
        integer(frame.get("sequence"), "sequence");
        requiredString(frame, "payload");
    }

    private static void validateEnvelope(Map<String, Object> envelope) {
        for (String field : List.of("version", "task_id", "intent", "capabilities", "input")) {
            required(envelope, field);
        }
        if (!VERSION.equals(envelope.get("version"))) {
            throw new ProtocolException("unsupported_envelope_version", "unsupported envelope version");
        }
        requiredString(envelope, "task_id");
        requiredString(envelope, "intent");
        Object capabilities = envelope.get("capabilities");
        if (!(capabilities instanceof List<?> capabilityList) || capabilityList.isEmpty()
            || capabilityList.stream().anyMatch(value -> !(value instanceof String s) || s.isEmpty())) {
            throw new ProtocolException("invalid_envelope", "capabilities must contain non-empty strings");
        }
        if (!(envelope.get("input") instanceof Map<?, ?>)) {
            throw new ProtocolException("invalid_envelope", "input must be an object");
        }
        optionalObject(envelope, "context");
        optionalObject(envelope, "policy");
        if (envelope.containsKey("memory_refs")) {
            Object refs = envelope.get("memory_refs");
            if (!(refs instanceof List<?> referenceList)
                || referenceList.stream().anyMatch(value -> !(value instanceof String))) {
                throw new ProtocolException("invalid_envelope", "memory_refs must be strings");
            }
        }
    }

    private static void validateStateDeltaPayload(
        Map<String, Object> delta, String stream, String previousMessage, BigInteger previousSequence
    ) {
        for (String field : List.of("event_id", "stream_id", "parent_event_id", "sequence", "kind", "payload")) {
            required(delta, field);
        }
        requiredString(delta, "event_id");
        if (!stream.equals(delta.get("stream_id")) || !previousMessage.equals(delta.get("parent_event_id"))) {
            throw new ProtocolException("broken_causality", "State Delta parent or stream is invalid");
        }
        if (integer(delta.get("sequence"), "delta sequence").compareTo(previousSequence) <= 0) {
            throw new ProtocolException("invalid_sequence", "State Delta sequence does not advance");
        }
        if (!"project_state.upsert".equals(delta.get("kind"))) {
            throw new ProtocolException("invalid_state_delta", "unsupported State Delta kind");
        }
        Map<String, Object> payload = asObject(delta.get("payload"), "State Delta payload");
        if (!stream.equals(payload.get("task_id"))) {
            throw new ProtocolException("invalid_state_delta", "State Delta task_id is invalid");
        }
    }

    private static void validateMemoryRecord(Map<String, Object> record) {
        requiredString(record, "id");
        requiredString(record, "kind");
        if (!(required(record, "content") instanceof Map<?, ?>)) {
            throw new ProtocolException("invalid_memory", "MemoryRecord content must be an object");
        }
        String portability = requiredString(record, "portability");
        if (!List.of("portable", "device_local", "ephemeral").contains(portability)) {
            throw new ProtocolException("invalid_memory", "unknown portability");
        }
        requiredString(record, "created_at");
    }

    private static void optionalObject(Map<String, Object> value, String field) {
        if (value.containsKey(field) && !(value.get(field) instanceof Map<?, ?>)) {
            throw new ProtocolException("invalid_envelope", field + " must be an object");
        }
    }

    private static Object required(Map<String, Object> value, String field) {
        if (!value.containsKey(field)) {
            throw new ProtocolException("invalid_envelope", "missing required field " + field);
        }
        return value.get(field);
    }

    private static String requiredString(Map<String, Object> value, String field) {
        Object item = required(value, field);
        if (!(item instanceof String text) || text.isEmpty()) {
            throw new ProtocolException("invalid_envelope", field + " must be a non-empty string");
        }
        return text;
    }

    private static BigInteger integer(Object value, String label) {
        if (!(value instanceof BigDecimal number) || number.scale() > 0 || number.signum() < 0) {
            throw new ProtocolException("invalid_sequence", label + " must be a non-negative integer");
        }
        try {
            return number.toBigIntegerExact();
        } catch (ArithmeticException error) {
            throw new ProtocolException("invalid_sequence", label + " is not an exact integer");
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asObject(Object value, String label) {
        if (!(value instanceof Map<?, ?> raw)) {
            throw new ProtocolException("malformed", label + " must be an object");
        }
        return (Map<String, Object>) raw;
    }

    private static Object parse(String text) {
        return new JsonParser(text).parseDocument();
    }

    private static String canonical(Object value) {
        StringBuilder result = new StringBuilder();
        writeCanonical(value, result);
        return result.toString();
    }

    private static final Comparator<String> CODE_POINT_ORDER = (left, right) -> {
        int leftIndex = 0;
        int rightIndex = 0;
        while (leftIndex < left.length() && rightIndex < right.length()) {
            int leftPoint = left.codePointAt(leftIndex);
            int rightPoint = right.codePointAt(rightIndex);
            if (leftPoint != rightPoint) {
                return Integer.compare(leftPoint, rightPoint);
            }
            leftIndex += Character.charCount(leftPoint);
            rightIndex += Character.charCount(rightPoint);
        }
        if (leftIndex == left.length() && rightIndex == right.length()) {
            return 0;
        }
        return leftIndex == left.length() ? -1 : 1;
    };

    @SuppressWarnings("unchecked")
    private static void writeCanonical(Object value, StringBuilder out) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String text) {
            writeString(text, out);
        } else if (value instanceof Boolean flag) {
            out.append(flag ? "true" : "false");
        } else if (value instanceof BigDecimal number) {
            out.append(number.stripTrailingZeros().toPlainString());
        } else if (value instanceof BigInteger number) {
            out.append(number.toString());
        } else if (value instanceof List<?> list) {
            out.append('[');
            for (int index = 0; index < list.size(); index++) {
                if (index > 0) out.append(',');
                writeCanonical(list.get(index), out);
            }
            out.append(']');
        } else if (value instanceof Map<?, ?> raw) {
            Map<String, Object> map = (Map<String, Object>) raw;
            List<String> keys = new ArrayList<>(map.keySet());
            Collections.sort(keys, CODE_POINT_ORDER);
            out.append('{');
            for (int index = 0; index < keys.size(); index++) {
                if (index > 0) out.append(',');
                String key = keys.get(index);
                writeString(key, out);
                out.append(':');
                writeCanonical(map.get(key), out);
            }
            out.append('}');
        } else {
            throw new ProtocolException("malformed", "unsupported JSON value");
        }
    }

    private static void writeString(String value, StringBuilder out) {
        validateUnicodeScalars(value);
        out.append('"');
        for (int index = 0; index < value.length();) {
            int point = value.codePointAt(index);
            index += Character.charCount(point);
            switch (point) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (point < 0x20) {
                        out.append(String.format("\\u%04x", point));
                    } else {
                        out.appendCodePoint(point);
                    }
                }
            }
        }
        out.append('"');
    }

    private static void validateUnicodeScalars(String value) {
        for (int index = 0; index < value.length(); index++) {
            char unit = value.charAt(index);
            if (Character.isHighSurrogate(unit)) {
                if (index + 1 >= value.length() || !Character.isLowSurrogate(value.charAt(index + 1))) {
                    throw new ProtocolException("malformed", "unpaired Unicode surrogate");
                }
                index++;
            } else if (Character.isLowSurrogate(unit)) {
                throw new ProtocolException("malformed", "unpaired Unicode surrogate");
            }
        }
    }

    private static final class JsonParser {
        private final String source;
        private int index;

        JsonParser(String source) {
            this.source = source;
        }

        Object parseDocument() {
            skipSpace();
            Object value = value();
            skipSpace();
            if (index != source.length()) throw error("unexpected trailing data");
            return value;
        }

        private Object value() {
            if (index >= source.length()) throw error("missing JSON value");
            return switch (source.charAt(index)) {
                case '{' -> object();
                case '[' -> array();
                case '"' -> string();
                case 't' -> literal("true", Boolean.TRUE);
                case 'f' -> literal("false", Boolean.FALSE);
                case 'n' -> literal("null", null);
                default -> number();
            };
        }

        private Map<String, Object> object() {
            expect('{');
            skipSpace();
            Map<String, Object> result = new LinkedHashMap<>();
            if (accept('}')) return result;
            while (true) {
                skipSpace();
                if (index >= source.length() || source.charAt(index) != '"') throw error("object key must be a string");
                String key = string();
                if (result.containsKey(key)) throw error("duplicate object key");
                skipSpace();
                expect(':');
                skipSpace();
                result.put(key, value());
                skipSpace();
                if (accept('}')) return result;
                expect(',');
            }
        }

        private List<Object> array() {
            expect('[');
            skipSpace();
            List<Object> result = new ArrayList<>();
            if (accept(']')) return result;
            while (true) {
                skipSpace();
                result.add(value());
                skipSpace();
                if (accept(']')) return result;
                expect(',');
            }
        }

        private String string() {
            expect('"');
            StringBuilder result = new StringBuilder();
            while (index < source.length()) {
                char unit = source.charAt(index++);
                if (unit == '"') {
                    String parsed = result.toString();
                    validateUnicodeScalars(parsed);
                    return parsed;
                }
                if (unit < 0x20) throw error("unescaped control character");
                if (unit != '\\') {
                    result.append(unit);
                    continue;
                }
                if (index >= source.length()) throw error("incomplete escape");
                char escaped = source.charAt(index++);
                switch (escaped) {
                    case '"', '\\', '/' -> result.append(escaped);
                    case 'b' -> result.append('\b');
                    case 'f' -> result.append('\f');
                    case 'n' -> result.append('\n');
                    case 'r' -> result.append('\r');
                    case 't' -> result.append('\t');
                    case 'u' -> result.append((char) hex4());
                    default -> throw error("invalid escape");
                }
            }
            throw error("unterminated string");
        }

        private Object literal(String expected, Object result) {
            if (!source.startsWith(expected, index)) throw error("invalid literal");
            index += expected.length();
            return result;
        }

        private BigDecimal number() {
            int start = index;
            if (accept('-')) {}
            if (accept('0')) {
                // A following digit is rejected below; JSON disallows 01.
            } else {
                digits();
            }
            if (accept('.')) digits();
            if (accept('e') || accept('E')) {
                if (accept('+') || accept('-')) {}
                digits();
            }
            String text = source.substring(start, index);
            try {
                return new BigDecimal(text);
            } catch (NumberFormatException error) {
                throw error("invalid number");
            }
        }

        private void digits() {
            int start = index;
            while (index < source.length() && Character.isDigit(source.charAt(index))) index++;
            if (index == start) throw error("expected digit");
        }

        private int hex4() {
            if (index + 4 > source.length()) throw error("incomplete Unicode escape");
            int value = 0;
            for (int count = 0; count < 4; count++) {
                int digit = Character.digit(source.charAt(index++), 16);
                if (digit < 0) throw error("invalid Unicode escape");
                value = (value << 4) | digit;
            }
            return value;
        }

        private boolean accept(char expected) {
            if (index < source.length() && source.charAt(index) == expected) {
                index++;
                return true;
            }
            return false;
        }

        private void expect(char expected) {
            if (!accept(expected)) throw error("expected '" + expected + "'");
        }

        private void skipSpace() {
            while (index < source.length() && Character.isWhitespace(source.charAt(index))) index++;
        }

        private ProtocolException error(String message) {
            return new ProtocolException("malformed", message + " at offset " + index);
        }
    }

    private static final class ProtocolException extends RuntimeException {
        final String code;

        ProtocolException(String code, String message) {
            super(message);
            this.code = code;
        }
    }

    private static void fail(String code, String message) {
        System.err.println("ERROR:" + code + ":" + message);
        System.exit(2);
    }
}
