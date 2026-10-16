import { describe, expect, it } from "vitest";
import { clampedOffset, directionAngle, handlePoint, resize } from "./geometry";

describe("geometry", () => {
  it("resizes from any handle and normalises", () => {
    expect(resize([10, 10, 50, 50], "se", { x: 60, y: 70 })).toEqual([10, 10, 60, 70]);
    expect(resize([10, 10, 50, 50], "n", { x: 0, y: 60 })).toEqual([10, 50, 50, 60]);
    expect(handlePoint([10, 10, 50, 50], "w")).toEqual({ x: 10, y: 30 });
  });

  it("keeps moved rects on the page", () => {
    expect(clampedOffset([[10, 10, 20, 20]], -50, 5, [0, 0, 100, 100])).toEqual({ x: -10, y: 5 });
    expect(clampedOffset([[10, 10, 20, 20]], 500, 500, [0, 0, 100, 100])).toEqual({ x: 80, y: 80 });
  });

  it("maps directions to angles", () => {
    expect(directionAngle([1, 0])).toBe(0);
    expect(directionAngle([0, -1])).toBe(90);
    expect(directionAngle([-1, 0])).toBe(180);
    expect(directionAngle([0, 1])).toBe(270);
    expect(directionAngle([0.7, 0.7])).toBeUndefined();
  });
});
