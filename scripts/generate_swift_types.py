"""Generate Swift Codable types from the FastAPI OpenAPI schema.

Usage:
    .venv/bin/python scripts/generate_swift_types.py ../Todo/Todo/Api/ApiTypes.swift

Reads the OpenAPI spec straight from the app factory (no running server needed)
and emits a single self-contained Swift file: one struct per Pydantic schema,
camelCase properties with CodingKeys, UUID/Date mapping, route constants and
JSON encoder/decoder configured for the server's datetime format.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import create_app  # noqa: E402

SKIP_SCHEMAS = {"HTTPValidationError", "ValidationError"}

HEADER = """\
// ApiTypes.swift
// GENERATED from the TodoApi OpenAPI schema — DO NOT EDIT.
// Regenerate: cd TodoApi && make swift-types

import Foundation
"""

JSON_HELPERS = """
/// JSON coding configured for TodoApi's datetime format
/// (naive UTC, e.g. "2026-08-17T09:00:00", optionally fractional / with offset).
enum TodoApiJSON {
    private static func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = format
        return f
    }

    private static let decodeFormats = [
        formatter("yyyy-MM-dd'T'HH:mm:ss.SSSSSS"),
        formatter("yyyy-MM-dd'T'HH:mm:ss.SSS"),
        formatter("yyyy-MM-dd'T'HH:mm:ss"),
        formatter("yyyy-MM-dd'T'HH:mm:ssZZZZZ"),
        formatter("yyyy-MM-dd'T'HH:mm:ss.SSSZZZZZ"),
        formatter("yyyy-MM-dd'T'HH:mm:ss.SSSSSSZZZZZ"),
    ]

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { d in
            let container = try d.singleValueContainer()
            let string = try container.decode(String.self)
            for format in decodeFormats {
                if let date = format.date(from: string) { return date }
            }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unrecognized date: \\(string)")
        }
        return decoder
    }()

    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        // Millisecond precision matters: the server resolves conflicts by
        // comparing updated_at, and whole seconds lose edits made in the same
        // second (a delete right after an edit used to be rejected this way).
        encoder.dateEncodingStrategy = .formatted(formatter("yyyy-MM-dd'T'HH:mm:ss.SSSZZZZZ"))
        return encoder
    }()
}
"""


class SwiftTypeGenerator:
    """OpenAPI components/schemas + paths → Swift source."""

    SCALARS = {
        "string": "String",
        "integer": "Int",
        "number": "Double",
        "boolean": "Bool",
    }

    def __init__(self, spec: dict):
        self.spec = spec
        self.schemas: dict = spec.get("components", {}).get("schemas", {})

    # ------------------------------------------------------------- helpers

    @staticmethod
    def camel(snake: str) -> str:
        head, *rest = snake.split("_")
        return head + "".join(part.capitalize() for part in rest)

    @classmethod
    def swift_type(cls, prop: dict) -> tuple[str, bool]:
        """Return (swift type, nullable)."""
        if "$ref" in prop:
            return prop["$ref"].rsplit("/", 1)[-1], False
        if "anyOf" in prop:
            inner = [p for p in prop["anyOf"] if p.get("type") != "null"]
            nullable = len(inner) != len(prop["anyOf"])
            if len(inner) == 1:
                name, _ = cls.swift_type(inner[0])
                return name, nullable
            return "String", nullable  # no mixed unions in this API
        ptype = prop.get("type")
        if ptype == "array":
            item, _ = cls.swift_type(prop.get("items", {}))
            return f"[{item}]", False
        if ptype == "string":
            fmt = prop.get("format", "")
            if fmt.startswith("uuid"):
                return "UUID", False
            if fmt == "date-time":
                return "Date", False
            return "String", False
        return cls.SCALARS.get(ptype, "String"), False

    @staticmethod
    def default_literal(prop: dict, swift_type: str, nullable: bool) -> str | None:
        if nullable:
            return "nil"
        if "default" not in prop:
            return None
        value = prop["default"]
        if swift_type.startswith("["):
            return "[]"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return f'"{value}"'
        return None

    # ------------------------------------------------------------- emitters

    def struct(self, name: str, schema: dict) -> str:
        properties: dict = schema.get("properties", {})
        lines = [f"struct {name}: Codable, Hashable, Sendable {{"]
        coding_keys: list[tuple[str, str]] = []

        for prop_name, prop in properties.items():
            swift_name = self.camel(prop_name)
            swift_type, nullable = self.swift_type(prop)
            coding_keys.append((swift_name, prop_name))
            declaration = f"    var {swift_name}: {swift_type}{'?' if nullable else ''}"
            default = self.default_literal(prop, swift_type, nullable)
            if default is not None:
                declaration += f" = {default}"
            lines.append(declaration)

        lines.append("")
        lines.append("    enum CodingKeys: String, CodingKey {")
        for swift_name, raw in coding_keys:
            if swift_name == raw:
                lines.append(f"        case {swift_name}")
            else:
                lines.append(f'        case {swift_name} = "{raw}"')
        lines.append("    }")
        lines.append("}")
        return "\n".join(lines)

    def routes(self) -> str:
        lines = [
            "/// Route constants derived from the OpenAPI paths.",
            "enum ApiRoutes {",
        ]
        for path, methods in self.spec.get("paths", {}).items():
            for method in methods:
                segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
                name = method.lower() + "".join(s.capitalize() for seg in segments for s in [self.camel(seg)])
                lines.append(f'    static let {name} = "{path}"  // {method.upper()}')
        lines.append("}")
        return "\n".join(lines)

    def generate(self) -> str:
        parts = [HEADER]
        for name, schema in self.schemas.items():
            if name in SKIP_SCHEMAS or schema.get("type") != "object":
                continue
            parts.append(self.struct(name, schema))
        parts.append(self.routes())
        parts.append(JSON_HELPERS)
        return "\n\n".join(parts) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <output.swift>")
    output = Path(sys.argv[1]).resolve()
    spec = create_app().openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(SwiftTypeGenerator(spec).generate())
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
