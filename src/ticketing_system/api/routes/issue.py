from fastapi import APIRouter, Request, HTTPException, Depends
from bson import ObjectId
from .. import utils
from .. import webhooks
import traceback
from typing import Annotated
from .. import auth
from .user import get_user_project_roles

router = APIRouter(prefix="/api")
db = utils.get_db_client()


@router.get("/issue/{issue_id}")
async def get_one(issue_id, user: auth.UserDep):
    issue = utils.prepare_json(db.issues.find_one({"_id": ObjectId(issue_id)}))
    if issue:
        user = db.users.find_one(
            {"discord_id": issue["playerData"]["id"]},
        )
        if user:
            issue["playerData"] = user

    return issue


@router.get("/issue/{issue_id}/modlogs")
async def get_one(user: auth.UserDep, issue_id):
    return utils.prepare_json(
        db.issues.find_one({"_id": ObjectId(issue_id)}, {"modlogs": 1})
    )


@router.post("/issue/findexact")
async def get_exact(user: auth.UserDep, request: Request):
    req_info = await request.json()
    if req_info.get("_id"):
        del req_info["_id"]

    return utils.prepare_json(db.issues.find_one(req_info))


@router.put("/issue/{issue_id}")
async def update_issue(user: auth.UserDep, issue_id, request: Request):
    req_info = await request.json()
    issue_id = ObjectId(issue_id)
    issue = utils.prepare_json(db.issues.find_one({"_id": issue_id}))
    project_roles = get_user_project_roles(
        user["discord_id"], project_id=issue["project_id"]
    )

    has_contributor = [i for i in project_roles if "contributor" in i["roles"]]

    if user["discord_id"] != issue["playerData"]["id"] or not has_contributor:
        raise HTTPException(
            status_code=403,
            detail="User does not have permissions to perform update on issue.",
        )

    issue_info = req_info["issue"]
    issue_info["category"] = issue_info["category"].lower()
    user_info = req_info["userInfo"]["data"]

    issue_info = {k: v for k, v in issue_info.items() if k != "playerData"}
    user_info = {k: user_info[k] for k in ["discord_id", "avatar", "username"]}

    issue_info.pop("id")

    issue = db.issues.find_one_and_update(
        {"_id": issue_id}, {"$set": issue_info}, upsert=False
    )

    diff = []

    for key, value in issue_info.items():
        if value == issue[key]:
            continue

        diff.append({"new": value, "old": issue[key], "key": key})

    webhooks.send_update_issue(diff, issue, user_info)

    return utils.prepare_json(issue)


@router.post("/issue")
async def create_issue(user: auth.UserDep, request: Request):
    req_info = await request.json()
    req_info["category"] = req_info["category"].lower()

    # TODO: check to see if user_id is allowed to create this issue on the project_name

    try:
        issue = db.issues.insert_one(req_info)
    except:
        print(traceback.format_exc())
        raise HTTPException(status_code=503, detail="Unable write issue to database")

    webhooks.send_new_issue(req_info)
    return utils.prepare_json(issue.inserted_id)


@router.delete("/issue/{issue_id}")
async def delete_issue(user: auth.UserDep, issue_id, request: Request):
    req_info = await request.json()
    user_info = {k: req_info[k] for k in ["discord_id", "avatar", "username"]}

    issue = db.issues.find_one({"_id": ObjectId(issue_id)})
    db.issues.find_one_and_delete({"_id": ObjectId(issue_id)})

    webhooks.send_deleted_issue(issue, user_info)
