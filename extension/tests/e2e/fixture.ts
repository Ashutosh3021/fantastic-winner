export const TWO_SUM_FIXTURE = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Two Sum - LeetCode</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 0; background: #fff; color: #111; }
      main { max-width: 52rem; margin: 2rem auto; padding: 0 1.5rem 4rem; }
      h1 { font-size: 1.5rem; }
      .monaco-editor { width: 100%; min-height: 10rem; border: 1px solid #ddd; padding: 0.5rem; }
      textarea { width: 100%; min-height: 8rem; font-family: monospace; }
      pre { background: #f6f6f6; padding: 0.75rem; overflow-x: auto; }
    </style>
  </head>
  <body>
    <main>
      <h1 data-e2e-locator="question-title">Two Sum</h1>
      <span data-e2e-locator="difficulty">Easy</span>
      <div data-e2e-locator="question-detail-container">
        <p>
          Given an array of integers nums and an integer target, return indices of the two
          numbers such that they add up to target.
        </p>
        <p>You may assume that each input would have exactly one solution, and you may not use the same element twice.</p>
        <p>You can return the answer in any order.</p>
        <pre>Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]
Explanation: Because nums[0] + nums[1] == 9, we return [0, 1].</pre>
        <p id="constraints">Constraints: 2 &lt;= nums.length &lt;= 10^4</p>
      </div>
      <a href="/tag/array/">Array</a>
      <a href="/tag/hash-table/">Hash Table</a>
      <div class="monaco-editor">
        <textarea aria-label="Editor content">class Solution:
    def twoSum(self, nums: list[int], target: int) -> list[int]:
        seen = {}
        for i, value in enumerate(nums):
            complement = target - value
            if complement in seen:
                return [seen[complement], i]
            seen[value] = i
        return []</textarea>
      </div>
    </main>
  </body>
</html>`;
